"""Weather and modelled soil moisture from Open-Meteo (free, no API key).

The design documents named OpenWeather, which needs a paid key for history.
Open-Meteo gives the current conditions, a 7-day forecast and the past 3 months
(rain and modelled soil moisture) in a single free request.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (description, icon name used by the front end)
WMO = {
    0: ("Clear sky", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloud"), 45: ("Fog", "fog"), 48: ("Rime fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "cloud"), 73: ("Snow", "cloud"), 75: ("Heavy snow", "cloud"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent showers", "storm"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}

_cache: dict = {}


def describe(code):
    return WMO.get(int(code) if code is not None else -1, ("Unknown", "cloud"))


def _openmeteo(lat, lon, timeout):
    import requests

    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "timezone": "auto",
        "past_days": 92,
        "forecast_days": 8,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,et0_fao_evapotranspiration",
        "hourly": "soil_moisture_3_to_9cm",
    }
    r = requests.get(FORECAST_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    hourly = data.get("hourly", {})
    soil_by_day: dict = {}
    for t, v in zip(hourly.get("time", []), hourly.get("soil_moisture_3_to_9cm", [])):
        if v is not None:
            soil_by_day.setdefault(t[:10], []).append(v)

    d = data["daily"]
    days = []
    for i, day in enumerate(d["time"]):
        soil = soil_by_day.get(day)
        days.append(
            {
                "date": day,
                "code": d["weather_code"][i],
                "tmax": d["temperature_2m_max"][i],
                "tmin": d["temperature_2m_min"][i],
                "rain_mm": d["precipitation_sum"][i],
                "rain_chance": (d.get("precipitation_probability_max") or [None] * len(d["time"]))[i],
                "et0_mm": (d.get("et0_fao_evapotranspiration") or [None] * len(d["time"]))[i],
                "soil_moisture": round(sum(soil) / len(soil), 3) if soil else None,
            }
        )
    c = data["current"]
    current = {
        "time": c.get("time"),
        "temperature": c.get("temperature_2m"),
        "humidity": c.get("relative_humidity_2m"),
        "wind_kmh": c.get("wind_speed_10m"),
        "code": c.get("weather_code"),
        "rain_mm": c.get("precipitation"),
    }
    return current, days


def _demo(lat, lon, today=None):
    """Plausible Botswana-style weather: hot wet summers, cool dry winters."""
    today = today or date.today()
    seed = int(hashlib.md5(f"{lat:.2f},{lon:.2f}".encode()).hexdigest()[:6], 16)
    days = []
    soil = 0.12
    for offset in range(-92, 8):
        d = today + timedelta(days=offset)
        doy = d.timetuple().tm_yday
        summer = math.cos((doy - 15) / 365 * 2 * math.pi)  # 1 in mid-January, -1 in mid-July
        h = int(hashlib.md5(f"{seed}{d}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
        wet_season = summer > 0.2
        rain = round((h * 28) if wet_season and h > 0.62 else (h * 4 if h > 0.93 else 0.0), 1)
        tmax = round(27 + 6 * summer + (h - 0.5) * 4 - rain * 0.15, 1)
        tmin = round(12 + 8 * summer + (h - 0.5) * 3, 1)
        et0 = round(4 + 2.5 * summer, 1)
        soil = min(0.38, max(0.07, soil + rain * 0.006 - et0 * 0.0025))
        code = 95 if rain > 18 else 63 if rain > 6 else 61 if rain > 0 else 2 if h > 0.5 else 0
        days.append(
            {
                "date": d.isoformat(), "code": code, "tmax": tmax, "tmin": tmin, "rain_mm": rain,
                "rain_chance": int(min(95, rain * 6 + (40 if wet_season else 5))) if offset >= 0 else None,
                "et0_mm": et0, "soil_moisture": round(soil, 3),
            }
        )
    t = next(x for x in days if x["date"] == today.isoformat())
    current = {
        "time": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "temperature": round((t["tmax"] + t["tmin"]) / 2 + 3, 1),
        "humidity": 35 + int(t["rain_mm"] * 2) % 50,
        "wind_kmh": round(8 + (seed % 10), 1),
        "code": t["code"],
        "rain_mm": t["rain_mm"],
    }
    return current, days


def get_weather(lat, lon, provider="auto", timeout=20):
    """Return {source, current, past (92 days), forecast (today + 7)}. Cached for 30 minutes."""
    key = (round(lat, 2), round(lon, 2), provider)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]

    source = "demo"
    if provider in ("auto", "openmeteo"):
        try:
            current, days = _openmeteo(lat, lon, timeout)
            source = "open-meteo"
        except Exception as exc:
            if provider == "openmeteo":
                raise
            log.warning("Open-Meteo not reachable (%s) - using demo weather", exc)
            current, days = _demo(lat, lon)
    else:
        current, days = _demo(lat, lon)

    today = date.today().isoformat()
    for item in [current] + days:
        item["description"], item["icon"] = describe(item.get("code"))
    result = {
        "source": source,
        "current": current,
        "past": [d for d in days if d["date"] < today],
        "forecast": [d for d in days if d["date"] >= today][:8],
    }
    _cache[key] = (time.time(), result)
    return result
