from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import label
from scipy.spatial import ConvexHull

from sargazo.config import DEFAULT_AFAI_THRESHOLD, DEFAULT_MIN_PIXELS
from sargazo.afai import GridProduct


@dataclass
class Patch:
    id: int
    n_pixels: int
    area_km2: float
    afai_mean: float
    afai_max: float
    lon: float
    lat: float
    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float
    hull: list[list[float]]


def _pixel_km2(lat: np.ndarray, resolution_deg: float) -> np.ndarray:
    km_lat = resolution_deg * 111.32
    km_lon = resolution_deg * 111.32 * np.cos(np.deg2rad(lat))
    return km_lat * km_lon


def extract_patches(
    product: GridProduct,
    threshold: float = DEFAULT_AFAI_THRESHOLD,
    min_pixels: int = DEFAULT_MIN_PIXELS,
) -> list[Patch]:
    mask = np.isfinite(product.afai) & (product.afai >= threshold)
    if not mask.any():
        return []
    labeled, n = label(mask)
    lat = product.lat
    lon = product.lon
    area_row = _pixel_km2(lat, product.resolution)
    patches: list[Patch] = []
    for pid in range(1, n + 1):
        cells = labeled == pid
        n_pix = int(cells.sum())
        if n_pix < min_pixels:
            continue
        rows, cols = np.where(cells)
        afai_vals = product.afai[cells]
        area = float(area_row[rows].sum())
        ys = lat[rows]
        xs = lon[cols]
        hull_coords = _hull(xs, ys)
        patches.append(
            Patch(
                id=len(patches) + 1,
                n_pixels=n_pix,
                area_km2=area,
                afai_mean=float(np.nanmean(afai_vals)),
                afai_max=float(np.nanmax(afai_vals)),
                lon=float(xs.mean()),
                lat=float(ys.mean()),
                lon_min=float(xs.min()),
                lat_min=float(ys.min()),
                lon_max=float(xs.max()),
                lat_max=float(ys.max()),
                hull=hull_coords,
            )
        )
    patches.sort(key=lambda p: p.area_km2, reverse=True)
    for i, patch in enumerate(patches, start=1):
        patch.id = i
    return patches


def _hull(xs: np.ndarray, ys: np.ndarray) -> list[list[float]]:
    points = np.column_stack([xs, ys])
    if len(points) < 3:
        lon0, lon1 = float(xs.min()), float(xs.max())
        lat0, lat1 = float(ys.min()), float(ys.max())
        pad = 0.01
        return [
            [lon0 - pad, lat0 - pad],
            [lon1 + pad, lat0 - pad],
            [lon1 + pad, lat1 + pad],
            [lon0 - pad, lat1 + pad],
            [lon0 - pad, lat0 - pad],
        ]
    try:
        hull = ConvexHull(points)
        verts = points[hull.vertices]
        closed = np.vstack([verts, verts[0]])
        return closed.tolist()
    except Exception:
        return [[float(xs.mean()), float(ys.mean())]]


def patches_to_geojson(patches: list[Patch]) -> dict:
    features = []
    for patch in patches:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": patch.id,
                    "area_km2": round(patch.area_km2, 2),
                    "n_pixels": patch.n_pixels,
                    "afai_mean": round(patch.afai_mean, 5),
                    "afai_max": round(patch.afai_max, 5),
                    "lon": round(patch.lon, 4),
                    "lat": round(patch.lat, 4),
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [patch.hull],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def patches_to_rows(patches: list[Patch]) -> list[dict]:
    return [
        {
            "id": p.id,
            "area_km2": round(p.area_km2, 2),
            "pixeles": p.n_pixels,
            "afai_medio": round(p.afai_mean, 5),
            "afai_max": round(p.afai_max, 5),
            "lon": round(p.lon, 4),
            "lat": round(p.lat, 4),
        }
        for p in patches
    ]
