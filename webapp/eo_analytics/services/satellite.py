"""Satellite crop-health (NDVI) and moisture (NDMI) analysis.

All imagery is real: Sentinel-2 Level-2A (10 m pixels, a new pass every ~5 days)
from Microsoft Planetary Computer. Free, no account or API key needed. This
replaces the Google Earth Engine prototype in Codes/Python_Modules, which needed
every user to have an Earth Engine login. If the service cannot be reached the
pages show an error; no data is ever simulated.

Indices
  NDVI = (NIR - Red) / (NIR + Red)      -> crop health / greenness   (B08, B04)
  NDMI = (NIR - SWIR) / (NIR + SWIR)    -> moisture in crops and soil (B08, B11)

Each scene result is cached on disk (small .npz) and its field averages in the
database, so the satellite is only queried once per field per date.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from . import geo

log = logging.getLogger(__name__)

# Colour ramp from the original Earth Engine app: red (poor) -> blue (excellent).
PALETTE = ["#FF0000", "#FF8000", "#FFFF00", "#00FF00", "#00FFFF", "#0000FF"]

INDEX_INFO = {
    "ndvi": {
        "label": "Crop Health",
        "min": 0.2,
        "max": 0.8,
        "classes": [("poor", 0.3), ("medium", 0.5)],  # >= last threshold is "good"
        "legend": ["Poor Health", "Medium", "Good Health"],
    },
    "ndmi": {
        "label": "Moisture",
        "min": -0.2,
        "max": 0.4,
        "classes": [("poor", 0.0), ("medium", 0.2)],
        "legend": ["Dry", "Medium", "Moist"],
    },
}

# Sentinel-2 scene classification (SCL) values we treat as a clear view of the ground:
# 4 vegetation, 5 bare soil, 6 water, 7 unclassified.
SCL_CLEAR = (4, 5, 6, 7)


class SatelliteUnavailable(RuntimeError):
    """The imagery service could not be reached."""


@dataclass
class Scene:
    id: str
    date: date
    cloud_cover: float
    payload: object = None  # provider specific (e.g. the STAC item)


@dataclass
class SceneArrays:
    ndvi: np.ndarray  # float32, NaN outside the field or under cloud
    ndmi: np.ndarray
    bbox: tuple  # lon/lat bounds of the arrays
    clear_fraction: float


# --------------------------------------------------------------------------- helpers


def lonlat_grid_shape(bbox, pixel_m=10.0, max_px=600):
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = math.radians((min_lat + max_lat) / 2)
    width_m = (max_lon - min_lon) * 111_320 * max(math.cos(mid_lat), 0.01)
    height_m = (max_lat - min_lat) * 110_540
    w = max(4, math.ceil(width_m / pixel_m))
    h = max(4, math.ceil(height_m / pixel_m))
    scale = max(w / max_px, h / max_px, 1.0)
    return max(4, int(h / scale)), max(4, int(w / scale))


def padded_bbox(geometry, pad_fraction=0.03):
    min_lon, min_lat, max_lon, max_lat = geo.bounds(geometry)
    dx = max((max_lon - min_lon) * pad_fraction, 0.0002)
    dy = max((max_lat - min_lat) * pad_fraction, 0.0002)
    return (min_lon - dx, min_lat - dy, max_lon + dx, max_lat + dy)


def polygon_mask(geometry, bbox, shape):
    """Boolean array, True for pixel centres inside the polygon (vectorised ray casting)."""
    ring = np.asarray(geo.outer_ring(geometry))
    h, w = shape
    min_lon, min_lat, max_lon, max_lat = bbox
    xs = min_lon + (np.arange(w) + 0.5) * (max_lon - min_lon) / w
    ys = max_lat - (np.arange(h) + 0.5) * (max_lat - min_lat) / h
    px, py = np.meshgrid(xs, ys)
    inside = np.zeros(shape, dtype=bool)
    x1, y1 = ring[:-1, 0], ring[:-1, 1]
    x2, y2 = ring[1:, 0], ring[1:, 1]
    for a, b, c, d in zip(x1, y1, x2, y2):
        crosses = (b > py) != (d > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = a + (py - b) * (c - a) / (d - b)
        inside ^= crosses & (px < x_at)
    return inside


def classify(values, index):
    """Share of the field (%) in poor / medium / good classes."""
    v = values[np.isfinite(values)]
    if v.size == 0:
        return None
    (_, t1), (_, t2) = INDEX_INFO[index]["classes"]
    poor = float(np.mean(v < t1) * 100)
    good = float(np.mean(v >= t2) * 100)
    return {"poor": round(poor, 1), "medium": round(100 - poor - good, 1), "good": round(good, 1)}


def colourise(values, index):
    """Render an index array as an RGBA PNG (transparent where NaN). Returns bytes."""
    info = INDEX_INFO[index]
    stops = np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in PALETTE], dtype=float)
    t = np.clip((values - info["min"]) / (info["max"] - info["min"]), 0, 1)
    t = np.nan_to_num(t, nan=0.0) * (len(stops) - 1)
    lo = np.floor(t).astype(int).clip(0, len(stops) - 2)
    frac = (t - lo)[..., None]
    rgb = stops[lo] * (1 - frac) + stops[lo + 1] * frac
    alpha = np.where(np.isfinite(values), 235, 0)[..., None]
    rgba = np.concatenate([rgb, alpha], axis=-1).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    # Upscale small fields so pixels look crisp instead of blurred by the browser.
    if max(img.size) < 400:
        factor = max(1, 400 // max(img.size))
        img = img.resize((img.width * factor, img.height * factor), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- providers


class PlanetaryComputerProvider:
    """Real Sentinel-2 L2A imagery from Microsoft Planetary Computer (no API key required)."""

    name = "sentinel-2"
    STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
    COLLECTION = "sentinel-2-l2a"

    def __init__(self, max_cloud_cover=60, timeout=20, min_clear=0.6):
        self.max_cloud_cover = max_cloud_cover
        self.timeout = timeout
        self.min_clear = min_clear

    def _catalog(self):
        try:
            import planetary_computer
            import pystac_client
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SatelliteUnavailable(
                "The satellite libraries are not installed on the server. "
                "Run: pip install rasterio pystac-client planetary-computer"
            ) from exc
        try:
            return pystac_client.Client.open(self.STAC_URL, modifier=planetary_computer.sign_inplace)
        except Exception as exc:
            raise SatelliteUnavailable(
                "Cannot reach the Sentinel-2 satellite service right now. Please try again in a few minutes."
            ) from exc

    def list_scenes(self, geometry, start, end):
        """One Scene per satellite pass date. A field near a tile edge can be covered by
        several tiles on the same day, so every tile is kept (clearest first)."""
        catalog = self._catalog()
        try:
            search = catalog.search(
                collections=[self.COLLECTION],
                intersects=geo.normalise_polygon(geometry),
                datetime=f"{start.isoformat()}/{end.isoformat()}",
                query={"eo:cloud_cover": {"lt": self.max_cloud_cover}},
                max_items=200,
            )
            items = list(search.items())
        except Exception as exc:
            log.warning("Sentinel-2 search failed: %s", exc)
            raise SatelliteUnavailable(
                "Cannot reach the Sentinel-2 satellite service right now. Please try again in a few minutes."
            ) from exc
        by_day = {}
        for item in items:
            by_day.setdefault(item.datetime.date(), []).append(item)
        scenes = []
        for d, day_items in by_day.items():
            day_items.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 100)))
            scenes.append(Scene(
                id=day_items[0].id, date=d,
                cloud_cover=float(day_items[0].properties.get("eo:cloud_cover", 100)),
                payload=day_items,
            ))
        return sorted(scenes, key=lambda s: s.date)

    def compute(self, geometry, scene, **_):
        """Field arrays for one pass date: tries each tile of that day until one sees the field clearly."""
        items = scene.payload if isinstance(scene.payload, list) else [scene.payload]
        if not items or items[0] is None:
            raise SatelliteUnavailable("Scene metadata missing; list scenes first.")
        best, last_error = None, None
        for item in items:
            try:
                arrays = self._compute_item(geometry, item)
            except SatelliteUnavailable as exc:
                last_error = exc
                continue
            if best is None or arrays.clear_fraction > best.clear_fraction:
                best = arrays
                scene.id = item.id
            if best.clear_fraction >= self.min_clear:
                break
        if best is None:
            raise last_error or SatelliteUnavailable(f"No readable tile for {scene.date}")
        return best

    def _compute_item(self, geometry, item):
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import from_bounds
        from rasterio.warp import reproject, transform_bounds
        from rasterio.windows import from_bounds as window_from_bounds

        bbox = padded_bbox(geometry)
        out_shape = lonlat_grid_shape(bbox)

        # Sentinel-2 processing baseline 04.00+ (from Jan 2022) adds +1000 to every value.
        baseline = str(item.properties.get("s2:processing_baseline", "00.00"))
        offset = 1000.0 if baseline >= "04.00" else 0.0

        env = dict(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
            GDAL_HTTP_TIMEOUT=str(self.timeout),
            GDAL_HTTP_MAX_RETRY="3",
            GDAL_HTTP_RETRY_DELAY="2",
        )
        bands = {}
        try:
            with rasterio.Env(**env):
                with rasterio.open(item.assets["B04"].href) as ref:
                    crs = ref.crs
                    nb = transform_bounds("EPSG:4326", crs, *bbox, densify_pts=21)
                    nw = max(4, math.ceil((nb[2] - nb[0]) / 10))
                    nh = max(4, math.ceil((nb[3] - nb[1]) / 10))
                    native_transform = from_bounds(*nb, nw, nh)
                for key in ("B04", "B08", "B11", "SCL"):
                    with rasterio.open(item.assets[key].href) as src:
                        win = window_from_bounds(*nb, transform=src.transform)
                        bands[key] = src.read(
                            1,
                            window=win,
                            out_shape=(nh, nw),
                            boundless=True,
                            fill_value=0,
                            resampling=Resampling.nearest if key == "SCL" else Resampling.bilinear,
                        ).astype(np.float32)
        except Exception as exc:
            log.warning("Reading %s failed: %s", item.id, exc)
            raise SatelliteUnavailable(f"Could not download imagery for {item.id}") from exc

        clear = np.isin(bands["SCL"], SCL_CLEAR)
        red = (bands["B04"] - offset) / 10000.0
        nir = (bands["B08"] - offset) / 10000.0
        swir = (bands["B11"] - offset) / 10000.0
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = (nir - red) / (nir + red)
            ndmi = (nir - swir) / (nir + swir)
        ndvi = np.where(clear, ndvi, np.nan).astype(np.float32)
        ndmi = np.where(clear, ndmi, np.nan).astype(np.float32)

        # Re-project onto a simple lon/lat grid so it lines up with the web map.
        dst_transform = from_bounds(*bbox, out_shape[1], out_shape[0])
        out = {}
        for key, arr in (("ndvi", ndvi), ("ndmi", ndmi)):
            dst = np.full(out_shape, np.nan, dtype=np.float32)
            reproject(
                arr, dst,
                src_transform=native_transform, src_crs=crs, src_nodata=np.nan,
                dst_transform=dst_transform, dst_crs="EPSG:4326", dst_nodata=np.nan,
                resampling=Resampling.nearest,
            )
            out[key] = dst

        inside = polygon_mask(geometry, bbox, out_shape)
        valid = inside & np.isfinite(out["ndvi"])
        clear_fraction = float(valid.sum() / max(inside.sum(), 1))
        ndvi_f = np.where(inside, out["ndvi"], np.nan)
        ndmi_f = np.where(inside, out["ndmi"], np.nan)
        return SceneArrays(ndvi=ndvi_f, ndmi=ndmi_f, bbox=bbox, clear_fraction=clear_fraction)


# --------------------------------------------------------------------------- service


class SatelliteService:
    """Fetches real Sentinel-2 imagery for fields, caches it and prepares what the pages need."""

    def __init__(self, config, cache_dir: Path):
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provider = PlanetaryComputerProvider(
            max_cloud_cover=config.get("MAX_CLOUD_COVER", 60),
            timeout=config.get("HTTP_TIMEOUT", 20),
            min_clear=config.get("MIN_CLEAR_FRACTION", 0.6),
        )

    # -- cache -----------------------------------------------------------
    def _npz_path(self, field_id, day, source):
        return self.cache_dir / f"field_{field_id}" / f"{day.isoformat()}_{source}.npz"

    def clear_field_cache(self, field_id):
        folder = self.cache_dir / f"field_{field_id}"
        if folder.exists():
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()

    def _save_arrays(self, field_id, day, source, arrays: SceneArrays):
        path = self._npz_path(field_id, day, source)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, ndvi=arrays.ndvi.astype(np.float16), ndmi=arrays.ndmi.astype(np.float16),
            bbox=np.array(arrays.bbox), clear=np.array([arrays.clear_fraction]),
        )

    def _load_arrays(self, field_id, day, source):
        path = self._npz_path(field_id, day, source)
        if not path.exists():
            return None
        data = np.load(path)
        return SceneArrays(
            ndvi=data["ndvi"].astype(np.float32), ndmi=data["ndmi"].astype(np.float32),
            bbox=tuple(float(v) for v in data["bbox"]), clear_fraction=float(data["clear"][0]),
        )

    # -- main operations --------------------------------------------------
    def update_readings(self, field, start, end, db, Reading, max_new=24):
        """Download any satellite passes between start and end not cached yet. Returns the source name.

        Raises SatelliteUnavailable if the service cannot be reached; nothing is ever made up.
        Passes that fail to download are not stored, so they are retried next time.
        """
        provider = self.provider
        geometry = field.geojson
        scenes = provider.list_scenes(geometry, start, end)

        have = {
            r.date for r in Reading.query.filter_by(field_id=field.id, source=provider.name).all()
        }
        todo = [s for s in scenes if s.date not in have][-max_new:]
        if not todo:
            return provider.name

        def work(scene):
            try:
                return scene, provider.compute(geometry, scene, crop=field.crop, planting=field.planting_date,
                                               field_key=f"{field.id}-{field.geometry}"), None
            except Exception as exc:  # one bad pass should not break the page
                log.warning("Scene %s failed: %s", scene.id, exc)
                return scene, None, exc

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(work, todo))

        min_clear = self.config.get("MIN_CLEAR_FRACTION", 0.6)
        failures = 0
        for scene, arrays, err in results:
            if err is not None:
                failures += 1
                continue
            usable = arrays.clear_fraction >= min_clear
            reading = Reading(
                field_id=field.id, date=scene.date, source=provider.name, scene_id=scene.id,
                clear_fraction=arrays.clear_fraction,
                ndvi_mean=float(np.nanmean(arrays.ndvi)) if usable else None,
                ndmi_mean=float(np.nanmean(arrays.ndmi)) if usable else None,
                ndvi_classes=json.dumps(classify(arrays.ndvi, "ndvi")) if usable else None,
                ndmi_classes=json.dumps(classify(arrays.ndmi, "ndmi")) if usable else None,
            )
            db.session.add(reading)
            if usable:
                self._save_arrays(field.id, scene.date, provider.name, arrays)
        db.session.commit()
        if failures and failures == len(results) and not have:
            raise SatelliteUnavailable(
                "Satellite images could not be downloaded right now. Please try again in a few minutes."
            )
        return provider.name

    def render(self, field, day, source, index):
        """PNG (as a data URL) for one field/date/index, plus its map bounds."""
        arrays = self._load_arrays(field.id, day, source)
        if arrays is None:
            return None
        values = arrays.ndvi if index == "ndvi" else arrays.ndmi
        png = colourise(values, index)
        min_lon, min_lat, max_lon, max_lat = arrays.bbox
        return {
            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "bounds": [[min_lat, min_lon], [max_lat, max_lon]],
        }


def season_window(today=None, months=3):
    today = today or date.today()
    return today - timedelta(days=int(months * 30.5)), today


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()
