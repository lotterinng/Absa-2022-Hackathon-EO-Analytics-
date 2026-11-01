"""JSON endpoints used by the pages' JavaScript."""
import json
import logging
from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

from .auth import login_required
from .models import Field, Reading, db, log_activity
from .services import geo, insights
from .services.satellite import INDEX_INFO, SatelliteUnavailable, parse_date, season_window
from .services.weather import WeatherUnavailable, get_weather

bp = Blueprint("api", __name__)
log = logging.getLogger(__name__)


def _sat():
    return current_app.extensions["satellite"]


def _field_or_404(field_id):
    field = db.session.get(Field, field_id)
    if field is None or (field.user_id != g.user.id and not g.user.is_admin):
        return None
    return field


def _err(message, status=400):
    return jsonify({"error": message}), status


def _field_from_payload(data, field=None):
    """Validate the body of a create/update request and apply it to a Field."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Please give the field a name.")
    crop = (data.get("crop") or "Other").strip()[:60]
    geometry = geo.normalise_polygon(data.get("geometry"))
    area = geo.area_hectares(geometry)
    if area < 0.05:
        raise ValueError("The field is too small (under 0.05 ha). Draw around the whole field.")
    if area > current_app.config["MAX_FIELD_HECTARES"]:
        raise ValueError(f"The field is too large (over {current_app.config['MAX_FIELD_HECTARES']:.0f} ha).")
    lat, lon = geo.centroid(geometry)
    expected = data.get("expected_yield_t_ha")
    expected = float(expected) if expected not in (None, "") else None
    if expected is not None and not (0 < expected < 500):
        raise ValueError("Expected yield must be a positive number of tonnes per hectare.")
    planting = data.get("planting_date") or None
    planting = parse_date(planting) if planting else None

    field = field or Field(user_id=g.user.id)
    geometry_changed = field.geometry != json.dumps(geometry)
    field.name = name[:120]
    field.crop = crop
    field.geometry = json.dumps(geometry)
    field.area_ha = area
    field.centroid_lat, field.centroid_lon = lat, lon
    field.expected_yield_t_ha = expected
    planting_changed = field.planting_date != planting
    field.planting_date = planting
    return field, geometry_changed or planting_changed


@bp.get("/fields")
@login_required
def list_fields():
    return jsonify([f.to_dict() for f in g.user.fields])


@bp.post("/fields")
@login_required
def create_field():
    try:
        field, _ = _field_from_payload(request.get_json(force=True) or {})
    except (ValueError, TypeError) as exc:
        return _err(str(exc))
    db.session.add(field)
    db.session.commit()
    log_activity(g.user, "field added", field.name)
    return jsonify(field.to_dict()), 201


@bp.put("/fields/<int:field_id>")
@login_required
def update_field(field_id):
    field = _field_or_404(field_id)
    if field is None:
        return _err("Field not found.", 404)
    try:
        field, changed = _field_from_payload(request.get_json(force=True) or {}, field)
    except (ValueError, TypeError) as exc:
        return _err(str(exc))
    if changed:
        Reading.query.filter_by(field_id=field.id).delete()
        _sat().clear_field_cache(field.id)
    db.session.commit()
    log_activity(g.user, "field updated", field.name)
    return jsonify(field.to_dict())


@bp.delete("/fields/<int:field_id>")
@login_required
def delete_field(field_id):
    field = _field_or_404(field_id)
    if field is None:
        return _err("Field not found.", 404)
    _sat().clear_field_cache(field.id)
    log_activity(g.user, "field deleted", field.name)
    db.session.delete(field)
    db.session.commit()
    return jsonify({"ok": True})


def _readings(field, months=3, end=None):
    """Bring the cache up to date for the window and return (source, readings as dicts)."""
    start, end = season_window(end, months)
    source = _sat().update_readings(field, start, end, db, Reading)
    rows = (
        Reading.query.filter(
            Reading.field_id == field.id, Reading.source == source,
            Reading.date >= start, Reading.date <= end,
        ).order_by(Reading.date).all()
    )
    return source, [r.to_dict() for r in rows]


@bp.get("/fields/<int:field_id>/analysis")
@login_required
def analysis(field_id):
    """Latest (or chosen) clear image for the field with its map overlay and recommendation."""
    field = _field_or_404(field_id)
    if field is None:
        return _err("Field not found.", 404)
    index = request.args.get("index", "ndvi")
    if index not in INDEX_INFO:
        return _err("Unknown index.")
    try:
        source, readings = _readings(field, months=3)
    except SatelliteUnavailable as exc:
        return _err(str(exc), 503)
    usable = [r for r in readings if r[index] is not None]
    if not usable:
        return jsonify({"field": field.to_dict(), "source": source, "reading": None,
                        "dates": [], "recommendation": insights.health_recommendation(None)})
    wanted = request.args.get("date")
    reading = next((r for r in usable if r["date"] == wanted), usable[-1])
    overlay = _sat().render(field, date.fromisoformat(reading["date"]), source, index)
    if index == "ndvi":
        rec = insights.health_recommendation(reading)
    else:
        weather = None
        try:
            weather = get_weather(field.centroid_lat, field.centroid_lon, current_app.config["HTTP_TIMEOUT"])
        except Exception:
            pass
        rec = insights.moisture_recommendation(reading, weather)
    info = INDEX_INFO[index]
    return jsonify({
        "field": field.to_dict(),
        "source": source,
        "index": index,
        "legend": {"min": info["min"], "max": info["max"], "labels": info["legend"], "label": info["label"]},
        "reading": reading,
        "overlay": overlay,
        "dates": [r["date"] for r in usable],
        "recommendation": rec,
    })


@bp.get("/fields/<int:field_id>/timeseries")
@login_required
def timeseries(field_id):
    field = _field_or_404(field_id)
    if field is None:
        return _err("Field not found.", 404)
    months = min(max(int(request.args.get("months", 3)), 1), 12)
    try:
        source, readings = _readings(field, months=months)
    except SatelliteUnavailable as exc:
        return _err(str(exc), 503)
    weather = None
    try:
        weather = get_weather(field.centroid_lat, field.centroid_lon, current_app.config["HTTP_TIMEOUT"])
    except Exception as exc:
        log.info("weather unavailable: %s", exc)
    usable = [r for r in readings if r["ndvi"] is not None]
    log_activity(g.user, "viewed statistics", field.name)
    return jsonify({
        "field": field.to_dict(),
        "source": source,
        "readings": usable,
        "weather_source": weather["source"] if weather else None,
        "soil": [{"date": d["date"], "soil_moisture": d["soil_moisture"], "rain_mm": d["rain_mm"]}
                 for d in (weather["past"] if weather else [])],
        "analysis": {
            "ndvi": insights.statistics_analysis(usable, "ndvi", "Crop health"),
            "ndmi": insights.statistics_analysis(usable, "ndmi", "Moisture"),
        },
        "yield": insights.yield_estimate(field, usable),
    })


@bp.get("/yield")
@login_required
def yield_all():
    """Yield estimate for every field of the signed-in farmer (Crop Yield tab)."""
    estimates = []
    source = None
    for field in g.user.fields:
        try:
            source, readings = _readings(field, months=6)
        except SatelliteUnavailable as exc:
            return _err(str(exc), 503)
        estimates.append(insights.yield_estimate(field, [r for r in readings if r["ndvi"] is not None]))
    log_activity(g.user, "viewed yield")
    return jsonify({"source": source, "fields": estimates,
                    "recommendation": insights.yield_recommendation(estimates)})


@bp.get("/weather")
@login_required
def weather():
    field = None
    if request.args.get("field"):
        field = _field_or_404(int(request.args["field"]))
    if field is None and g.user.fields:
        field = g.user.fields[0]
    if field is not None:
        lat, lon, place = field.centroid_lat, field.centroid_lon, field.name
    else:
        lat, lon, place = -24.6282, 25.9231, "Gaborone"
    try:
        data = get_weather(lat, lon, current_app.config["HTTP_TIMEOUT"])
    except WeatherUnavailable as exc:
        return _err(str(exc), 503)
    return jsonify({**data, "place": place, "lat": lat, "lon": lon})
