"""Dashboard data access and API payload assembly.

Ported as-is from the previous stdlib main.py: dashboard state (weather
cache, irrigation history, pump acks, site config) lives in flat files under
data/, written by weather_mqtt.py's scheduled/ack-listener processes and by
api_config_save() below. This module owns reading/validating that state for
dashboard/views.py; it deliberately doesn't touch the ORM/models, since the
web layer is being made Django-shaped without changing what it does yet.
"""
import csv
import json
import math
import re
import subprocess
import sys
import time

from django.conf import settings

from .i18n import DEFAULT_LANG, LANGS

BASE_DIR = settings.BASE_DIR
DATA_DIR = BASE_DIR / "data"

WEATHER_CACHE = DATA_DIR / "weather_cache.json"
NEXT_WATERING = DATA_DIR / "next_watering.json"
IRRIGATION_CSV = DATA_DIR / "irrigation_history.csv"
PUMP_ACKS = DATA_DIR / "pump_acks.json"
SITE_CONFIG = DATA_DIR / "site_config.json"
SITE_CONFIG_FIELDS = ("station", "broker", "root_topic", "lang")
WEATHER_MQTT_SCRIPT = BASE_DIR / "weather_mqtt.py"
REFRESH_TIMEOUT_SECONDS = 90

# Any 4-letter ICAO airport code is accepted -- weather_mqtt.py resolves its
# lat/lon (from METAR) and tz (reverse-geocoded via Open-Meteo) dynamically
# and caches the result, so this process only needs to validate the shape of
# the code, not maintain a registry of known stations.
ICAO_RE = re.compile(r"^[A-Z]{4}$")
DEFAULT_STATION = "ZSNJ"


def current_lang() -> str:
    """The site-wide UI language: whatever was last saved via the config
    panel, else DEFAULT_LANG. Always one of LANGS -- an unset or corrupted
    site_config.json falls back rather than crashing the page render."""
    if SITE_CONFIG.exists():
        try:
            lang = json.loads(SITE_CONFIG.read_text(encoding="utf-8")).get("lang")
            if lang in LANGS:
                return lang
        except Exception:
            pass
    return DEFAULT_LANG


def api_status() -> dict:
    if not WEATHER_CACHE.exists():
        return _demo_status()

    data = json.loads(WEATHER_CACHE.read_text(encoding="utf-8"))
    loc = data.setdefault("location", {})
    station = _effective_station()
    loc.setdefault("station", station)
    # location.station_name is only refreshed by the tri-hourly full run;
    # current.station_name comes from the hourly METAR-only refresh and is
    # usually fresher after switching to a new airport, so prefer it. Bare
    # code is the last resort, e.g. right after switching before either has
    # run once against the new station.
    current_station_name = (data.get("current") or {}).get("station_name")
    loc["city"] = loc.get("station_name") or current_station_name or station

    # Supplement with next_watering.json for freshest event list
    if NEXT_WATERING.exists():
        nw = json.loads(NEXT_WATERING.read_text(encoding="utf-8"))
        sched = (data.get("irrigation") or {}).get("schedule") or {}
        if isinstance(sched, dict):
            sched.setdefault("json_payload", nw)

    return data


def api_history(n: int = 14) -> dict:
    if not IRRIGATION_CSV.exists():
        return {"rows": _demo_history()}
    with IRRIGATION_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {"rows": rows[-n:]}


def api_acks() -> dict:
    if not PUMP_ACKS.exists():
        return {"devices": {}}
    data = json.loads(PUMP_ACKS.read_text(encoding="utf-8"))
    return {"devices": data.get("devices") or {}}


def api_config_get() -> dict:
    if not SITE_CONFIG.exists():
        cfg = {k: "" for k in SITE_CONFIG_FIELDS}
        cfg["lang"] = DEFAULT_LANG
        cfg["station"] = DEFAULT_STATION
        return cfg
    try:
        data = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    cfg = {k: data.get(k, "") for k in SITE_CONFIG_FIELDS}
    cfg["lang"] = cfg["lang"] if cfg["lang"] in LANGS else DEFAULT_LANG
    station = str(cfg["station"] or "").strip().upper()
    cfg["station"] = station if ICAO_RE.match(station) else DEFAULT_STATION
    return cfg


def api_config_save(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")

    cfg = {}
    station = str(payload.get("station") or "").strip().upper()
    if station and not ICAO_RE.match(station):
        raise ValueError("'station' must be a 4-letter ICAO airport code (e.g. ZSNJ, KJFK, EGLL).")
    cfg["station"] = station
    for key in ("broker", "root_topic"):
        v = payload.get(key, "")
        cfg[key] = "" if v is None else str(v).strip()
    lang = str(payload.get("lang") or "").strip()
    if lang and lang not in LANGS:
        raise ValueError(f"'lang' must be one of {', '.join(LANGS)}.")
    cfg["lang"] = lang or DEFAULT_LANG

    tmp = SITE_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SITE_CONFIG)

    return cfg


def api_refresh() -> dict:
    """Manual dashboard refresh button: re-fetch Yr.no/OWM/Open-Meteo/METAR
    right now via `weather_mqtt.py --fetch-only`, which refreshes the
    forecast/current/ensemble sections of weather_cache.json but -- unlike a
    normal scheduled run -- never recomputes the irrigation decision, never
    touches irrigation_history.csv/next_watering.json, and never publishes to
    the MQTT broker (so it can't accidentally command a pump or consume a due
    watering event outside the normal 3-hourly cadence). See that flag's
    --help and run_fetch_only()'s docstring for the full reasoning."""
    try:
        proc = subprocess.run(
            [sys.executable, str(WEATHER_MQTT_SCRIPT), "--fetch-only"],
            capture_output=True, text=True, timeout=REFRESH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Refresh timed out after {REFRESH_TIMEOUT_SECONDS}s.")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[-500:] or "weather_mqtt.py --fetch-only failed.")
    return api_status()


def _effective_station() -> str:
    """Same override order weather_mqtt.py uses: an explicit site_config.json
    value first, else whatever station the last successful forecast run
    resolved to, else DEFAULT_STATION."""
    if SITE_CONFIG.exists():
        try:
            station = str(json.loads(SITE_CONFIG.read_text(encoding="utf-8")).get("station") or "").strip().upper()
            if ICAO_RE.match(station):
                return station
        except Exception:
            pass
    if WEATHER_CACHE.exists():
        try:
            station = str((json.loads(WEATHER_CACHE.read_text(encoding="utf-8")).get("location") or {}).get("station") or "").strip().upper()
            if ICAO_RE.match(station):
                return station
        except Exception:
            pass
    return DEFAULT_STATION


# ── Demo data (shown when no cache files exist yet) ───────────────────────────

def _demo_status() -> dict:
    now = int(time.time())
    next_epoch = now + 29 * 3600
    following_epoch = next_epoch + 2 * 86400

    return {
        "_demo": True,
        "generated_at": "2026-06-30T14:23:00",
        "next_run_epoch": int(time.time()) + 3 * 3600,
        "location": {"lat": 31.7420, "lon": 118.8622, "tz": "Asia/Shanghai", "station": DEFAULT_STATION, "city": "Nanjing Lukou Intl (ZSNJ)"},
        "horizon_hours": 120,
        "status": {"source_mode": "ENSEMBLE_AVG_YR+OWM+OM", "yr_ok": True, "owm_ok": True, "om_ok": True},
        "current": {
            "source": "METAR",
            "station": DEFAULT_STATION,
            "station_name": "Nanjing Lukou Intl (ZSNJ)",
            "obs_time_epoch": now - 8 * 60,
            "age_minutes": 8.0,
            "temp_c": 29,
            "dewpoint_c": 24,
            "rh_pct": 71.6,
            "wind_mps": 3.1,
            "wind_dir_deg": 220,
            "pressure_hpa": 1003,
            "vpd_kpa": 1.02,
            "raw_ob": "METAR ZSNJ 301400Z 22006MPS 9999 BKN026 29/24 Q1003 NOSIG",
        },
        "irrigation": {
            "decision_percent": 75,
            "decision_label": "REDUCED",
            "pump_seconds": 90,
            "overall_outlook": (
                "some rain next 24 h; estimated 0–24 h demand 3.21 mm; "
                "recommendation: reduce irrigation to 75%."
            ),
            "summary": (
                "No drench commanded today. Temperature cadence = 2.00 days. "
                "event#1 2026-07-01T05:10:00+08:00 (sunrise) → 75% / 90 s"
            ),
            "schedule": {
                "decision_code": "WAIT",
                "tmin24_c": 24.3,
                "tmean72_c": 27.1,
                "tmax24_c": 33.1,
                "next_watering_epoch": next_epoch,
                "projected_following_epoch": following_epoch,
                "schedule_armed": True,
                "json_payload": {
                    "events": [
                        {
                            "sequence": 1,
                            "epoch": next_epoch,
                            "iso_local": "2026-07-01T05:10:00+08:00",
                            "solar_anchor": "sunrise",
                            "percent": 75,
                            "pump_seconds": 90,
                            "percent_basis": "forecast_fractional",
                        },
                        {
                            "sequence": 2,
                            "epoch": following_epoch,
                            "iso_local": "2026-07-03T05:14:00+08:00",
                            "solar_anchor": "sunrise",
                            "percent": 60,
                            "pump_seconds": 72,
                            "percent_basis": "forecast_fractional",
                        },
                    ]
                },
            },
        },
        "ensemble": {
            "rain_mm": {
                "r12": 0.3, "r24": 1.8, "r72": 5.2,
                "r24_48": 2.1, "r48_72": 1.3,
            },
            "demand_mm": {"d0_24": 3.21, "d24_48": 2.87, "d48_72": 2.54},
            "future_credit": {"cover_ratio_0_1": 0.41, "multiplier": 0.79},
            "decision_debug": {
                "pct_base": 95, "pct_final": 75, "exposure_factor": 0.75,
                "rain_index_mm": 1.24, "start_reduce_mm": 0.79, "full_skip_mm": 3.99,
            },
            "climate_debug": {
                "t_mean_24h_c": 28.5,
                "rh_mean_24h_pct": 64.2,
                "wind_mean_24h_mps": 2.1,
                "vpd_kpa": 0.82,
                "daylength_h": 14.2,
                "t_min_12h_c": 24.3,
                "demand_mm_24h": 3.21,
                "baseline_pump_seconds_normal": 120,
            },
        },
        "sources": {
            "yr":  {"rain_mm": {"r12": 0.2, "r24": 1.5, "r72": 4.8}, "demand_mm": {"d0_24": 3.15, "d24_48": 2.80, "d48_72": 2.50}},
            "owm": {"rain_mm": {"r12": 0.4, "r24": 2.1, "r72": 5.6}, "demand_mm": {"d0_24": 3.27, "d24_48": 2.94, "d48_72": 2.58}},
            "om":  {"rain_mm": {"r12": 0.3, "r24": 1.8, "r72": 5.1}, "demand_mm": {"d0_24": 3.20, "d24_48": 2.86, "d48_72": 2.53}},
        },
        "comparison": {"rows": _demo_forecast_rows()},
    }


def _demo_forecast_rows() -> list:
    rows = []
    now = int(time.time())
    for i in range(24):
        h = i * 3
        t_owm = 26.0 + 5.0 * math.sin(math.pi * (h - 6) / 12) + i * 0.06
        t_yr  = t_owm + 0.8 * math.sin(math.pi * i / 12)
        t_om  = t_owm - 0.5 * math.sin(math.pi * i / 10)
        rh    = 65 - 10 * math.sin(math.pi * (h - 6) / 12)
        rain_owm = 0.0 if h < 12 else (1.5 if h < 18 else 0.4)
        rain_yr  = 0.0 if h < 14 else (1.2 if h < 18 else 0.3)
        rain_om  = 0.0 if h < 13 else (1.3 if h < 18 else 0.5)
        rows.append({
            "local_time": f"06-30 {h:02d}:00",
            "epoch": now + h * 3600,
            "owm_temp_c": round(t_owm, 1),
            "yr_temp_c":  round(t_yr, 1),
            "om_temp_c":  round(t_om, 1),
            "owm_rh_pct": round(rh),
            "yr_rh_pct":  round(rh + 3),
            "om_rh_pct":  round(rh - 2),
            "owm_wind_mps": round(1.5 + 0.5 * math.sin(math.pi * i / 8), 1),
            "yr_wind_mps":  round(1.8 + 0.3 * math.sin(math.pi * i / 8), 1),
            "om_wind_mps":  round(1.6 + 0.4 * math.sin(math.pi * i / 8), 1),
            "owm_rain_3h_mm": round(rain_owm, 1),
            "yr_rain_3h_mm":  round(rain_yr, 1),
            "om_rain_3h_mm":  round(rain_om, 1),
            "owm_desc": "light rain" if rain_owm > 0 else "clear sky",
            "yr_sym":   "rainshowers_day" if rain_yr > 0 else "clearsky_day",
            "om_desc":  "rain" if rain_om > 0 else "clear sky",
        })
    return rows


def _demo_history() -> list:
    return [
        {"local_date": "2026-06-23", "decision_code": "DRENCH",     "decision_label": "NORMAL",  "commanded_percent": "100", "commanded_pump_seconds": "120", "forecast_precip_local_day_mm": "0.0",  "forecast_tmin24_c": "22.1", "forecast_tmax24_c": "31.2"},
        {"local_date": "2026-06-25", "decision_code": "DRENCH",     "decision_label": "REDUCED", "commanded_percent": "80",  "commanded_pump_seconds": "96",  "forecast_precip_local_day_mm": "2.3",  "forecast_tmin24_c": "23.4", "forecast_tmax24_c": "30.1"},
        {"local_date": "2026-06-27", "decision_code": "DRENCH",     "decision_label": "SKIP",    "commanded_percent": "0",   "commanded_pump_seconds": "0",   "forecast_precip_local_day_mm": "12.5", "forecast_tmin24_c": "20.8", "forecast_tmax24_c": "26.4"},
        {"local_date": "2026-06-29", "decision_code": "DRENCH",     "decision_label": "LIGHT",   "commanded_percent": "40",  "commanded_pump_seconds": "48",  "forecast_precip_local_day_mm": "0.8",  "forecast_tmin24_c": "24.2", "forecast_tmax24_c": "32.8"},
        {"local_date": "2026-06-30", "decision_code": "WAIT",       "decision_label": "SKIP",    "commanded_percent": "0",   "commanded_pump_seconds": "0",   "forecast_precip_local_day_mm": "1.8",  "forecast_tmin24_c": "24.3", "forecast_tmax24_c": "33.1"},
    ]
