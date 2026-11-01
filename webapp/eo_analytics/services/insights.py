"""Plain-language recommendations and the crop-yield estimate.

These are rules of thumb, not agronomic advice. They turn the satellite numbers
into the short "Recommendations" and "Analysis" cards shown in the mock-ups.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

# Peak NDVI a healthy, well-managed crop usually reaches at full canopy,
# and a typical expected yield (t/ha) used when the farmer leaves it blank.
CROPS = {
    "Maize": (0.80, 2.5),
    "Sorghum": (0.72, 1.5),
    "Pearl millet": (0.65, 1.0),
    "Cowpeas": (0.70, 0.8),
    "Groundnuts": (0.70, 1.0),
    "Sunflower": (0.75, 1.0),
    "Sweet reed": (0.68, 15.0),
    "Watermelon": (0.62, 15.0),
    "Vegetables": (0.75, 10.0),
    "Pasture": (0.65, 3.0),
    "Other": (0.72, 1.5),
}
BARE_NDVI = 0.15  # NDVI of bare soil / no crop
ACTIVE_CROP_NDVI = 0.32  # below this all season long we assume no crop is growing


def crop_reference(crop):
    return CROPS.get(crop, CROPS["Other"])


def _pct(x):
    return f"{round(x)}%"


def health_recommendation(reading):
    if not reading or reading.get("ndvi") is None:
        return "No clear satellite image of this field yet. Check again after the next satellite pass (about every 5 days)."
    c = reading["ndvi_classes"] or {}
    ndvi = reading["ndvi"]
    good, medium, poor = c.get("good", 0), c.get("medium", 0), c.get("poor", 0)
    if ndvi < ACTIVE_CROP_NDVI and poor > 60:
        return (
            f"Most of the field ({_pct(poor)}) shows little green growth. If the crop has not emerged yet or "
            "the field is fallow this is expected. If it is planted, walk the red areas to check for poor "
            "germination, pests or water stress."
        )
    if good >= 60:
        msg = f"Most of the crops are in good health ({_pct(good)} of the field)."
        if poor > 10:
            msg += f" About {_pct(poor)} is in poor health — inspect the red patches on the map for pests, weeds or waterlogging."
        else:
            msg += " Keep up the current management."
        return msg
    if poor >= 30:
        return (
            f"{_pct(poor)} of the field is in poor health. Compare with the Soil Moisture view: if the same "
            "areas are dry, irrigation or mulching should help; if they are moist, check for nutrient deficiency, "
            "pests or disease."
        )
    return (
        f"Crop health is mostly medium ({_pct(medium)} of the field). This may be due to low soil moisture "
        "or nutrients. Check the Soil Moisture view and consider top-dressing fertiliser where crops look pale."
    )


def moisture_recommendation(reading, weather=None):
    if not reading or reading.get("ndmi") is None:
        return "No clear satellite image of this field yet. Check again after the next satellite pass."
    c = reading["ndmi_classes"] or {}
    dry, moist = c.get("poor", 0), c.get("good", 0)
    rain_next = None
    if weather and weather.get("forecast"):
        rain_next = sum((d.get("rain_mm") or 0) for d in weather["forecast"][:3])
    if dry >= 50:
        msg = f"Most of the field ({_pct(dry)}) has low moisture."
        if rain_next is not None and rain_next >= 10:
            msg += f" About {rain_next:.0f} mm of rain is forecast in the next 3 days, so you may be able to delay irrigation."
        else:
            msg += " Better irrigation or mulching would help keep moisture in the soil."
        return msg
    if moist >= 50:
        return f"Moisture is good across {_pct(moist)} of the field. Avoid over-irrigating; watch low spots for waterlogging."
    return "Moisture is moderate. Focus irrigation on the red and orange areas of the map, which are drying first."


def yield_estimate(field, readings, today=None):
    """Indicative yield from how green the crop got this season compared with a healthy crop.

    Returns a dict, or a dict with status "no-crop" / "no-data".
    """
    today = today or date.today()
    ref_peak, default_yield = crop_reference(field.crop)
    expected_t_ha = field.expected_yield_t_ha or default_yield
    season_start = field.planting_date or (today - timedelta(days=150))
    season = [r for r in readings if r["ndvi"] is not None and date.fromisoformat(r["date"]) >= season_start]
    base = {
        "field_id": field.id, "field": field.name, "crop": field.crop,
        "area_ha": round(field.area_ha, 1), "expected_t_ha": expected_t_ha,
        "expected_total_t": round(expected_t_ha * field.area_ha, 1),
    }
    if len(season) < 2:
        return {**base, "status": "no-data"}
    values = sorted(r["ndvi"] for r in season)
    peak = mean(values[-3:]) if len(values) >= 3 else values[-1]
    if peak < ACTIVE_CROP_NDVI:
        return {**base, "status": "no-crop", "peak_ndvi": round(peak, 2)}
    index = max(0.0, min(1.15, (peak - BARE_NDVI) / (ref_peak - BARE_NDVI)))
    latest = season[-1]["ndvi"]
    growing = latest >= peak - 0.03  # still at/near the high point -> season not finished
    return {
        **base,
        "status": "ok",
        "peak_ndvi": round(peak, 2),
        "reference_ndvi": ref_peak,
        "current_pct": round(index * 100),
        "estimated_t_ha": round(expected_t_ha * index, 2),
        "estimated_total_t": round(expected_t_ha * index * field.area_ha, 1),
        "growing": growing,
    }


def yield_recommendation(estimates):
    ok = [e for e in estimates if e["status"] == "ok"]
    if not ok:
        if any(e["status"] == "no-crop" for e in estimates):
            return "No actively growing crop was detected this season. Yield estimates will appear once your crops green up."
        return "Not enough clear satellite images yet to estimate yield. Add your planting date to each field for a better estimate."
    low = [e for e in ok if e["current_pct"] < 80]
    if not low:
        return "All fields are on track for their expected yield. Keep monitoring crop health and soil moisture weekly."
    names = ", ".join(f"{e['field']} ({e['crop']}, {e['current_pct']}%)" for e in low)
    return (
        f"Below expected: {names}. Improving soil moisture and nutrition during the growing period will help "
        "crop health and, eventually, the yield."
    )


def statistics_analysis(readings, key, label):
    """Month-by-month summary for the Statistics page."""
    rows = [r for r in readings if r.get(key) is not None]
    if len(rows) < 2:
        return [f"Not enough clear images in the last 3 months to analyse {label.lower()}."]
    by_month: dict = {}
    for r in rows:
        by_month.setdefault(r["date"][:7], []).append(r[key])
    months = sorted(by_month)
    lines = []
    names = {m: date.fromisoformat(m + "-01").strftime("%B") for m in months}
    avg = {m: mean(v) for m, v in by_month.items()}
    first, last = months[0], months[-1]
    lines.append(f"In {names[first]} the average {label.lower()} index was {avg[first]:.2f}.")
    for prev, cur in zip(months, months[1:]):
        change = avg[cur] - avg[prev]
        if abs(change) < 0.02:
            lines.append(f"It stayed about the same in {names[cur]} ({avg[cur]:.2f}).")
        elif change > 0:
            lines.append(f"It rose to {avg[cur]:.2f} in {names[cur]} (+{change:.2f}).")
        else:
            lines.append(f"It dropped to {avg[cur]:.2f} in {names[cur]} ({change:.2f}).")
    best = max(rows, key=lambda r: r[key])
    lines.append(f"The highest value was {best[key]:.2f} on {date.fromisoformat(best['date']).strftime('%d %B')}.")
    if key == "ndvi" and avg[last] < avg[first] - 0.05:
        lines.append("A falling trend outside harvest time can point to water stress — compare with the Soil Moisture tab.")
    return lines
