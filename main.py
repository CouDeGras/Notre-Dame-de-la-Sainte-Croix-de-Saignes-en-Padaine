#!/usr/bin/env python3
"""
Fuenteazahar weather dashboard — stdlib-only HTTP server.
Run: python3 main.py [--port 8080]
"""
import argparse
import csv
import json
import math
import mimetypes
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import jinja2

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
TMPL_DIR = BASE_DIR / "templates"

WEATHER_CACHE = DATA_DIR / "weather_cache.json"
NEXT_WATERING = DATA_DIR / "next_watering.json"
IRRIGATION_CSV = DATA_DIR / "irrigation_history.csv"
PUMP_ACKS = DATA_DIR / "pump_acks.json"
SITE_CONFIG = DATA_DIR / "site_config.json"
SITE_CONFIG_FIELDS = ("station", "broker", "root_topic", "lang")
WEATHER_MQTT_SCRIPT = BASE_DIR / "weather_mqtt.py"
REFRESH_TIMEOUT_SECONDS = 90

DEFAULT_LANG = "en"
LANGS = ("en", "fr", "it")

# Any 4-letter ICAO airport code is accepted -- weather_mqtt.py resolves its
# lat/lon (from METAR) and tz (reverse-geocoded via Open-Meteo) dynamically
# and caches the result, so this process only needs to validate the shape of
# the code, not maintain a registry of known stations.
ICAO_RE = re.compile(r"^[A-Z]{4}$")
DEFAULT_STATION = "ZSNJ"

# All user-facing text, keyed by ISO language code. Consumed two ways: the
# Jinja template reads `t.*` directly for text baked into the server-rendered
# HTML, and the same dict is dumped as JSON into a `window.I18N` script tag
# so app.js's dynamically-rendered content (table rows, countdown, config
# modal feedback) can look up strings without a second source of truth.
STRINGS = {
    "en": {
        "title_suffix": "Irrigation",
        "subtitle": "Automatic irrigation",
        "refresh_title": "Refresh",
        "config_title": "Settings",
        "close": "Close",
        "field_station": "Airport code (ICAO)",
        "field_station_hint": "4-letter ICAO code of your nearest airport, e.g. KJFK, EGLL, ZSNJ.",
        "field_broker": "MQTT Broker",
        "field_topic": "Root topic",
        "field_lang": "Language",
        "btn_cancel": "Cancel",
        "btn_save": "Save",
        "card_next_irrigation": "Next irrigation",
        "next_reading": "Next reading",
        "card_history": "Irrigation history",
        "card_pump_nodes": "Pump nodes",
        "metric_temp": "Temp.",
        "metric_rh": "Humidity",
        "metric_rh_sub": "airport obs.",
        "metric_wind": "Wind",
        "metric_vpd": "VPD",
        "metric_demand": "Demand",
        "th_date": "Date", "th_decision": "Decision", "th_pct": "%",
        "th_pump_s": "Pump (s)", "th_rain_mm": "Rain (mm)", "th_tmin": "T min", "th_tmax": "T max",
        "th_node": "Node", "th_seen": "Seen", "th_executed": "Executed", "th_armed": "Armed",
        "chart_owm": "OWM precipitation and temperature",
        "chart_yr": "Yr.no precipitation and temperature",
        "chart_om": "Open-Meteo precipitation and temperature",
        "legend_temp": "TEMP.", "legend_irrig": "IRRIG", "legend_precip": "3HPA",
        "loading": "Loading…",
        "decision_drench": "WATER", "decision_wait": "WAIT", "decision_freeze": "FROST",
        "anchor_sunrise": "SUNRISE", "anchor_sunset": "SUNSET",
        "now": "NOW", "yes": "YES", "no": "NO",
        "no_acks": "No pump node has sent an ACK yet.",
        "no_history": "No history yet — run weather_mqtt.py.",
        "just_now": "just now",
        "saving": "Saving…", "error": "Error",
    },
    "fr": {
        "title_suffix": "Irrigation",
        "subtitle": "Irrigation automatique",
        "refresh_title": "Actualiser",
        "config_title": "Configuration",
        "close": "Fermer",
        "field_station": "Code aéroport (OACI)",
        "field_station_hint": "Code OACI à 4 lettres de l'aéroport le plus proche, ex. KJFK, EGLL, ZSNJ.",
        "field_broker": "Broker MQTT",
        "field_topic": "Sujet racine",
        "field_lang": "Langue",
        "btn_cancel": "Annuler",
        "btn_save": "Enregistrer",
        "card_next_irrigation": "Prochain arrosage",
        "next_reading": "Prochaine lecture",
        "card_history": "Historique d'arrosage",
        "card_pump_nodes": "Nœuds de pompe",
        "metric_temp": "Temp.",
        "metric_rh": "Humidité",
        "metric_rh_sub": "obs. aéroport",
        "metric_wind": "Vent",
        "metric_vpd": "VPD",
        "metric_demand": "Besoin",
        "th_date": "Date", "th_decision": "Décision", "th_pct": "%",
        "th_pump_s": "Pompe (s)", "th_rain_mm": "Pluie (mm)", "th_tmin": "T min", "th_tmax": "T max",
        "th_node": "Nœud", "th_seen": "Vu", "th_executed": "Exécuté", "th_armed": "Armé",
        "chart_owm": "Précipitations et température OWM",
        "chart_yr": "Précipitations et température Yr.no",
        "chart_om": "Précipitations et température Open-Meteo",
        "legend_temp": "TEMP.", "legend_irrig": "ARROS.", "legend_precip": "3HPA",
        "loading": "Chargement…",
        "decision_drench": "ARROSAGE", "decision_wait": "ATTENTE", "decision_freeze": "GEL",
        "anchor_sunrise": "LEVER", "anchor_sunset": "COUCHER",
        "now": "MAINTENANT", "yes": "OUI", "no": "NON",
        "no_acks": "Aucun nœud de pompe n'a encore envoyé d'ACK.",
        "no_history": "Aucun historique — exécutez weather_mqtt.py.",
        "just_now": "à l'instant",
        "saving": "Enregistrement…", "error": "Erreur",
    },
    "it": {
        "title_suffix": "Irrigazione",
        "subtitle": "Irrigazione automatica",
        "refresh_title": "Aggiorna",
        "config_title": "Configurazione",
        "close": "Chiudi",
        "field_station": "Codice aeroporto (ICAO)",
        "field_station_hint": "Codice ICAO di 4 lettere dell'aeroporto più vicino, es. KJFK, EGLL, ZSNJ.",
        "field_broker": "Broker MQTT",
        "field_topic": "Argomento radice",
        "field_lang": "Lingua",
        "btn_cancel": "Annulla",
        "btn_save": "Salva",
        "card_next_irrigation": "Prossima irrigazione",
        "next_reading": "Prossima lettura",
        "card_history": "Storico irrigazione",
        "card_pump_nodes": "Nodi pompa",
        "metric_temp": "Temp.",
        "metric_rh": "Umidità",
        "metric_rh_sub": "oss. aeroporto",
        "metric_wind": "Vento",
        "metric_vpd": "VPD",
        "metric_demand": "Fabbisogno",
        "th_date": "Data", "th_decision": "Decisione", "th_pct": "%",
        "th_pump_s": "Pompa (s)", "th_rain_mm": "Pioggia (mm)", "th_tmin": "T min", "th_tmax": "T max",
        "th_node": "Nodo", "th_seen": "Visto", "th_executed": "Eseguito", "th_armed": "Armato",
        "chart_owm": "Precipitazioni e temperatura OWM",
        "chart_yr": "Precipitazioni e temperatura Yr.no",
        "chart_om": "Precipitazioni e temperatura Open-Meteo",
        "legend_temp": "TEMP.", "legend_irrig": "IRRIG.", "legend_precip": "3HPA",
        "loading": "Caricamento…",
        "decision_drench": "IRRIGA", "decision_wait": "ATTESA", "decision_freeze": "GELO",
        "anchor_sunrise": "ALBA", "anchor_sunset": "TRAMONTO",
        "now": "ORA", "yes": "SÌ", "no": "NO",
        "no_acks": "Nessun nodo pompa ha ancora inviato un ACK.",
        "no_history": "Nessuno storico — eseguire weather_mqtt.py.",
        "just_now": "adesso",
        "saving": "Salvataggio…", "error": "Errore",
    },
}

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TMPL_DIR)),
    autoescape=True,
)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # quieter logs
        print(f"  {self.address_string()} {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_template("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/status":
            self._serve_json(_api_status())
        elif path == "/api/history":
            qs = parse_qs(parsed.query)
            n = int(qs.get("n", ["14"])[0])
            self._serve_json(_api_history(n))
        elif path == "/api/acks":
            self._serve_json(_api_acks())
        elif path == "/api/config":
            self._serve_json(_api_config_get())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/config":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, "text/plain", b"Invalid JSON")
                return
            try:
                saved = _api_config_save(payload)
            except ValueError as e:
                self._send(400, "text/plain", str(e).encode())
                return
            self._serve_json(saved)
        elif path == "/api/refresh":
            try:
                data = _api_refresh()
            except RuntimeError as e:
                self._send(502, "text/plain", str(e).encode())
                return
            self._serve_json(data)
        else:
            self._send(404, "text/plain", b"Not found")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _serve_template(self, name: str):
        try:
            tmpl = _jinja_env.get_template(name)
            lang = _current_lang()
            strings = STRINGS[lang]
            i18n_json = json.dumps(strings, ensure_ascii=False).replace("</", "<\\/")
            body = tmpl.render(lang=lang, t=strings, i18n_json=i18n_json).encode()
            self._send(200, "text/html; charset=utf-8", body)
        except Exception as e:
            self._send(500, "text/plain", str(e).encode())

    def _serve_static(self, rel: str):
        p = STATIC_DIR / rel
        if not p.exists() or not p.is_file():
            self._send(404, "text/plain", b"Not found")
            return
        mime, _ = mimetypes.guess_type(str(p))
        self._send(200, mime or "application/octet-stream", p.read_bytes())

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self._send(200, "application/json; charset=utf-8", body)

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# ── API handlers ─────────────────────────────────────────────────────────────

def _api_status() -> dict:
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


def _api_history(n: int = 14) -> dict:
    if not IRRIGATION_CSV.exists():
        return {"rows": _demo_history()}
    with IRRIGATION_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {"rows": rows[-n:]}


def _api_acks() -> dict:
    if not PUMP_ACKS.exists():
        return {"devices": {}}
    data = json.loads(PUMP_ACKS.read_text(encoding="utf-8"))
    return {"devices": data.get("devices") or {}}


def _current_lang() -> str:
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


def _api_config_get() -> dict:
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


def _api_config_save(payload: dict) -> dict:
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


def _api_refresh() -> dict:
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
    return _api_status()


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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fuenteazahar dashboard server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    addr = (args.host, args.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    print(f"Dashboard running at http://localhost:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
