"""Simulated Sentinel-2 provider used ONLY by the automated tests (no internet needed).

The application itself always uses real imagery.
"""
import hashlib
import math
from datetime import date, timedelta

import numpy as np

from eo_analytics.services.satellite import Scene, SceneArrays, lonlat_grid_shape, padded_bbox, polygon_mask


class FakeProvider:
    """Simulated Sentinel-2 passes. Deterministic, so the same field always looks the same."""

    name = "sentinel-2"
    revisit_days = 5

    def list_scenes(self, geometry, start, end):
        scenes = []
        anchor = date(2020, 1, 3)
        d = anchor + timedelta(days=((start - anchor).days // self.revisit_days + 1) * self.revisit_days)
        while d <= end:
            seed = int(hashlib.md5(d.isoformat().encode()).hexdigest()[:8], 16)
            cloud = (seed % 100) * (0.9 if d.month in (5, 6, 7, 8, 9) else 1.0)
            if cloud < 70:
                scenes.append(Scene(id=f"DEMO_{d:%Y%m%d}", date=d, cloud_cover=round(cloud * 0.5, 1)))
            d += timedelta(days=self.revisit_days)
        return scenes

    @staticmethod
    def season_ndvi(day, planting=None):
        """Typical rain-fed crop curve for southern Africa (planting Nov, peak Feb, harvest May)."""
        if planting is None:
            planting = date(day.year if day.month >= 10 else day.year - 1, 11, 20)
        t = (day - planting).days
        if t < 0 or t > 220:
            return 0.18  # dry-season bare / stubble field
        green_up = 1 / (1 + math.exp(-(t - 45) / 9))
        senesce = 1 / (1 + math.exp((t - 140) / 12))
        return 0.18 + 0.62 * green_up * senesce

    def compute(self, geometry, scene, crop=None, planting=None, field_key=""):
        bbox = padded_bbox(geometry)
        shape = lonlat_grid_shape(bbox, max_px=220)
        inside = polygon_mask(geometry, bbox, shape)
        h, w = shape
        rng = np.random.default_rng(int(hashlib.md5(field_key.encode()).hexdigest()[:8], 16))
        yy, xx = np.mgrid[0:h, 0:w] / max(h, w)
        # Smooth within-field pattern (soil differences, a wetter corner, a weak strip).
        pattern = np.zeros(shape)
        for _ in range(5):
            fx, fy, ph = rng.uniform(1, 4), rng.uniform(1, 4), rng.uniform(0, 6.28)
            pattern += np.sin(fx * 6.28 * xx + ph) * np.cos(fy * 6.28 * yy + ph / 2)
        pattern /= np.abs(pattern).max() or 1
        day_noise = np.random.default_rng(scene.date.toordinal() + len(field_key)).normal(0, 0.02, shape)
        vigour = rng.uniform(0.72, 1.0)  # some fields simply do better than others
        cx, cy = rng.uniform(0.2, 0.8, 2)  # one stressed patch (e.g. a sandy or waterlogged spot)
        pattern -= 1.6 * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / 0.03))
        base = 0.18 + (self.season_ndvi(scene.date, planting) - 0.18) * vigour
        amplitude = 0.04 + 0.16 * (base - 0.18) / 0.62
        ndvi = np.clip(base + amplitude * pattern + day_noise, -0.1, 0.95)
        rain = 0.06 * math.sin(scene.date.toordinal() / 9.0)  # wet/dry spells
        ndmi = np.clip(0.75 * ndvi - 0.22 + rain + 0.08 * pattern + day_noise, -0.5, 0.7)
        ndvi = np.where(inside, ndvi, np.nan).astype(np.float32)
        ndmi = np.where(inside, ndmi, np.nan).astype(np.float32)
        return SceneArrays(ndvi=ndvi, ndmi=ndmi, bbox=bbox, clear_fraction=1.0)
