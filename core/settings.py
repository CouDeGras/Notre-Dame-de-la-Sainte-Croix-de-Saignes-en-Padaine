"""Django settings for the Saignes-en-Padaine dashboard.

This project intentionally keeps the same runtime shape as the stdlib
version it replaces: a single process, no reverse proxy, bound to 0.0.0.0
and reached over plain HTTP on the LAN (see saignes-dashboard.service).
Most dashboard state (weather cache, pump acks, site config) still lives in
flat files under data/, read/written by dashboard/services.py. Irrigation
decisions and METAR history live in the ORM instead (dashboard/models.py),
written by weather_mqtt.py -- a separate, non-web process that bootstraps
Django itself (django.setup()) purely to share this one schema definition.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Matches the OWM_APPID pattern already used in weather_mqtt.py: an
# env-var override with a hardcoded fallback, since this single-user LAN
# dashboard has no secret-management story beyond "it's on the local box".
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-saignes-en-padaine-6f3a9c1e8b2d47f6a5c0e2b7d1a94f60",
)

# The original main.py had no debug/production distinction (it just ran a
# ThreadingHTTPServer) and returned raw exception text on errors -- DEBUG=True
# here preserves that behavior and lets `runserver` serve static/ without a
# separate collectstatic step. Override with DJANGO_DEBUG=0 once this app
# grows real auth/control endpoints worth hardening.
DEBUG = os.getenv("DJANGO_DEBUG", "1") != "0"

# Reached via LAN IP and mDNS hostname (see saignes-dashboard.xml), not a
# fixed domain, so -- same as the old server binding 0.0.0.0 with no host
# check -- accept any Host header.
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# Backs Django's own auth/sessions/admin, plus dashboard.models'
# IrrigationDecision/MetarReading (irrigation + METAR history, written by
# weather_mqtt.py -- a separate OS process -- and read here). WAL mode
# because that makes this a genuine multi-process concurrent-access
# database (one writer process, one reader process) rather than SQLite's
# usual single-process case; WAL substantially cuts "database is locked"
# errors between the two.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The dashboard itself is multilingual (en/fr/it, see dashboard/i18n.py) but
# that's an app-level concept driven by data/site_config.json, independent
# of Django's own USE_I18N machinery.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
