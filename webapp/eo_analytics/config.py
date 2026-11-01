"""Application settings.

Every value can be overridden with an environment variable of the same name,
so the same code runs on a laptop, a server or in Docker without edits.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Change SECRET_KEY in production: it signs the login cookies.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'eo_analytics.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # "planetary" = real Sentinel-2 imagery from Microsoft Planetary Computer (free, no key).
    # "demo"      = realistic simulated data, works with no internet connection.
    # "auto"      = try real data first, fall back to demo if it cannot be reached.
    SATELLITE_PROVIDER = os.environ.get("SATELLITE_PROVIDER", "auto")
    # "openmeteo" (free, no key), "demo", or "auto".
    WEATHER_PROVIDER = os.environ.get("WEATHER_PROVIDER", "auto")

    # Max cloud cover (%) of a Sentinel-2 scene before it is skipped.
    MAX_CLOUD_COVER = int(os.environ.get("MAX_CLOUD_COVER", "40"))
    # Share of the field that must be cloud-free in a scene for it to count.
    MIN_CLEAR_FRACTION = float(os.environ.get("MIN_CLEAR_FRACTION", "0.6"))
    # Largest field accepted, in hectares (keeps satellite downloads small).
    MAX_FIELD_HECTARES = float(os.environ.get("MAX_FIELD_HECTARES", "5000"))

    # Comma separated RSS feeds shown on the Agric News page next to admin posts.
    NEWS_FEEDS = [
        f.strip()
        for f in os.environ.get(
            "NEWS_FEEDS",
            "https://www.fao.org/news/rss-feed/en/,"
            "https://www.agriculture.com/rss/news",
        ).split(",")
        if f.strip()
    ]

    # The first account registered with this e-mail becomes an administrator.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()

    # Optional SMTP for password-reset mails. Without it the reset link is shown
    # on screen (development) and written to the server log.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@eo-analytics.local")
    SHOW_RESET_LINK = _bool("SHOW_RESET_LINK", True)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)

    HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "20"))
