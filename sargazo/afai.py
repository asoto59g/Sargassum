from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from scipy.ndimage import binary_dilation, gaussian_filter
from scipy.stats import binned_statistic_2d

from sargazo.config import (
    AFAI_LAMBDAS,
    COAST_BUFFER_PX,
    DEFAULT_FLAG_MASK,
    GRID_RES_DEG,
)


@dataclass
class GranuleMeta:
    path: Path
    product: str
    title: str
    time_start: str
    lat_min: float | None
    lat_max: float | None
    lon_min: float | None
    lon_max: float | None
    wavelengths: list[float]
    groups: list[str]
    notes: list[str] = field(default_factory=list)

    def intersects_bbox(self, bbox: tuple[float, float, float, float]) -> bool | None:
        if None in (self.lat_min, self.lat_max, self.lon_min, self.lon_max):
            return None
        west, south, east, north = bbox
        if self.lat_max < south or self.lat_min > north:
            return False
        if self.lon_min <= self.lon_max:
            return not (self.lon_max < west or self.lon_min > east)
        return self.lon_max >= west or self.lon_min <= east


@dataclass
class SwathAFAI:
    path: Path
    time_start: str
    latitude: np.ndarray
    longitude: np.ndarray
    afai: np.ndarray
    rgb: tuple[np.ndarray, np.ndarray, np.ndarray] | None
    used_wavelengths: tuple[float, float, float]


@dataclass
class GridProduct:
    west: float
    south: float
    east: float
    north: float
    resolution: float
    afai: np.ndarray
    coverage: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    times: list[str]
    used_wavelengths: tuple[float, float, float]
    files: list[str]


def _attr(obj, name: str, default=""):
    try:
        value = getattr(obj, name)
    except AttributeError:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def describe_nc(path: Path) -> GranuleMeta:
    notes: list[str] = []
    with Dataset(path) as nc:
        title = str(_attr(nc, "title", path.name))
        product = str(_attr(nc, "product_name", path.name))
        time_start = str(_attr(nc, "time_coverage_start", ""))
        groups = list(nc.groups)
        lat_min = _maybe_float(_attr(nc, "geospatial_lat_min", None))
        lat_max = _maybe_float(_attr(nc, "geospatial_lat_max", None))
        lon_min = _maybe_float(_attr(nc, "geospatial_lon_min", None))
        lon_max = _maybe_float(_attr(nc, "geospatial_lon_max", None))
        wavelengths: list[float] = []
        if "sensor_band_parameters" in nc.groups:
            sbp = nc.groups["sensor_band_parameters"]
            if "wavelength_3d" in sbp.variables:
                wavelengths = [
                    float(v) for v in np.array(sbp.variables["wavelength_3d"][:])
                ]
        if "OC_AOP" in product or "OC_AOP" in title or "Apparent Optical" in title:
            notes.append(
                "Este archivo es OC_AOP (Rrs). PACE Rrs solo llega ~719 nm y "
                "no incluye 748 ni 869 nm, así que no se puede calcular AFAI."
            )
            notes.append(
                "Usa PACE OCI L2 SFREFL (rhos). Ese producto sí tiene 667, 748 y 869 nm."
            )
        if wavelengths:
            wmax = max(wavelengths)
            if wmax < 740:
                notes.append(
                    f"Longitud de onda máxima = {wmax:.0f} nm. AFAI necesita ~869 nm."
                )
    return GranuleMeta(
        path=path,
        product=product,
        title=title,
        time_start=time_start,
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        wavelengths=wavelengths,
        groups=groups,
        notes=notes,
    )


def _maybe_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nearest_index(wavelengths: np.ndarray, target: float) -> tuple[int, float]:
    idx = int(np.argmin(np.abs(wavelengths.astype(float) - target)))
    return idx, float(wavelengths[idx])


def _flag_lookup(flags_var) -> dict[str, int]:
    meanings = str(_attr(flags_var, "flag_meanings", "")).split()
    masks = np.array(_attr(flags_var, "flag_masks", []), dtype=np.int64)
    if len(meanings) != len(masks):
        return {}
    return {name: int(mask) for name, mask in zip(meanings, masks)}


def _quality_mask(flags: np.ndarray, lookup: dict[str, int], names: tuple[str, ...]) -> np.ndarray:
    bad = 0
    for name in names:
        bad |= lookup.get(name, 0)
    if bad == 0:
        return np.ones(flags.shape, dtype=bool)
    return (flags.astype(np.int64) & bad) == 0


def _ocean_mask(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    from global_land_mask import globe

    lat_f = np.clip(lat.astype(float), -90, 90)
    lon_f = ((lon.astype(float) + 180) % 360) - 180
    valid = np.isfinite(lat_f) & np.isfinite(lon_f)
    ocean = np.zeros(lat.shape, dtype=bool)
    if not valid.any():
        return ocean
    ocean[valid] = globe.is_ocean(lat_f[valid], lon_f[valid])
    return ocean


def can_compute_afai(path: Path) -> tuple[bool, str]:
    meta = describe_nc(path)
    if not meta.wavelengths:
        return False, "No se encontraron longitudes de onda (wavelength_3d)."
    if max(meta.wavelengths) < 740:
        return False, (
            "El producto no llega a 748/869 nm. Necesitas PACE L2 SFREFL, no OC_AOP."
        )
    name = path.name.upper()
    if "SFREFL" not in name and "OC_AOP" in name:
        return False, "Archivo OC_AOP: usa SFREFL para AFAI."
    return True, "OK"


def read_swath_afai(
    path: Path,
    bbox: tuple[float, float, float, float] | None = None,
    mask_flags: tuple[str, ...] = DEFAULT_FLAG_MASK,
    mask_land_flag: bool = True,
    include_rgb: bool = True,
) -> SwathAFAI:
    ok, reason = can_compute_afai(path)
    if not ok:
        raise ValueError(reason)

    with Dataset(path) as nc:
        time_start = str(_attr(nc, "time_coverage_start", path.name))
        geo = nc.groups["geophysical_data"]
        nav = nc.groups["navigation_data"]
        sbp = nc.groups["sensor_band_parameters"]
        wavelengths = np.array(sbp.variables["wavelength_3d"][:], dtype=float)
        lat = np.array(nav.variables["latitude"][:], dtype=np.float32)
        lon = np.array(nav.variables["longitude"][:], dtype=np.float32)

        if "rhos" in geo.variables:
            refl = geo.variables["rhos"]
        elif "Rrs" in geo.variables:
            refl = geo.variables["Rrs"]
        else:
            raise ValueError("El archivo no contiene rhos ni Rrs.")

        idxs = []
        used = []
        for target in AFAI_LAMBDAS:
            idx, actual = _nearest_index(wavelengths, target)
            idxs.append(idx)
            used.append(actual)

        r1 = np.array(refl[:, :, idxs[0]], dtype=np.float32)
        r2 = np.array(refl[:, :, idxs[1]], dtype=np.float32)
        r3 = np.array(refl[:, :, idxs[2]], dtype=np.float32)

        rgb = None
        if include_rgb:
            ir = _nearest_index(wavelengths, 665)[0]
            ig = _nearest_index(wavelengths, 560)[0]
            ib = _nearest_index(wavelengths, 443)[0]
            rgb = (
                np.array(refl[:, :, ir], dtype=np.float32),
                np.array(refl[:, :, ig], dtype=np.float32),
                np.array(refl[:, :, ib], dtype=np.float32),
            )

        flags = np.array(geo.variables["l2_flags"][:], dtype=np.int32)
        lookup = _flag_lookup(geo.variables["l2_flags"])
        names = mask_flags + (("LAND",) if mask_land_flag else ())
        qmask = _quality_mask(flags, lookup, names)

    lam1, lam2, lam3 = used
    baseline = r1 + (r3 - r1) * ((lam2 - lam1) / (lam3 - lam1))
    afai = r2 - baseline

    valid = (
        qmask
        & np.isfinite(afai)
        & np.isfinite(r1)
        & np.isfinite(r2)
        & np.isfinite(r3)
        & (r1 > -0.05)
        & (r1 < 1.5)
        & (r2 > -0.05)
        & (r2 < 1.5)
        & (r3 > -0.05)
        & (r3 < 1.5)
    )
    ocean = _ocean_mask(lat, lon)
    valid &= ocean

    if bbox is not None:
        west, south, east, north = bbox
        valid &= (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)

    afai = np.where(valid, afai, np.nan)
    if rgb is not None:
        rgb = tuple(np.where(valid, band, np.nan) for band in rgb)

    return SwathAFAI(
        path=path,
        time_start=time_start,
        latitude=lat,
        longitude=lon,
        afai=afai,
        rgb=rgb,
        used_wavelengths=(lam1, lam2, lam3),
    )


def grid_swaths(
    swaths: list[SwathAFAI],
    bbox: tuple[float, float, float, float],
    resolution: float = GRID_RES_DEG,
    coast_buffer_px: int = COAST_BUFFER_PX,
) -> GridProduct:
    west, south, east, north = bbox
    lon_edges = np.arange(west, east + resolution, resolution)
    lat_edges = np.arange(south, north + resolution, resolution)
    ny, nx = len(lat_edges) - 1, len(lon_edges) - 1
    acc = np.full((ny, nx), -np.inf, dtype=np.float32)
    coverage = np.zeros((ny, nx), dtype=np.int16)

    used = swaths[0].used_wavelengths if swaths else AFAI_LAMBDAS
    times: list[str] = []

    for swath in swaths:
        times.append(swath.time_start)
        mask = np.isfinite(swath.afai)
        if not mask.any():
            continue
        lon = swath.longitude[mask].astype(np.float64)
        lat = swath.latitude[mask].astype(np.float64)
        val = swath.afai[mask].astype(np.float64)
        stat, _, _, _ = binned_statistic_2d(
            lon,
            lat,
            val,
            statistic="max",
            bins=[lon_edges, lat_edges],
        )
        count, _, _, _ = binned_statistic_2d(
            lon,
            lat,
            val,
            statistic="count",
            bins=[lon_edges, lat_edges],
        )
        # binned_statistic_2d returns (nx, ny)
        grid = np.array(stat.T, dtype=np.float32)
        cnt = np.array(count.T, dtype=np.int16)
        better = np.isfinite(grid) & (grid > acc)
        acc[better] = grid[better]
        coverage += (cnt > 0).astype(np.int16)

    acc[np.isneginf(acc)] = np.nan

    lon_c = 0.5 * (lon_edges[:-1] + lon_edges[1:])
    lat_c = 0.5 * (lat_edges[:-1] + lat_edges[1:])
    lon2d, lat2d = np.meshgrid(lon_c, lat_c)
    ocean = _ocean_mask(lat2d, lon2d)
    if coast_buffer_px > 0:
        land = ~ocean
        ocean = ~binary_dilation(land, iterations=int(coast_buffer_px))
    acc = np.where(ocean, acc, np.nan)

    return GridProduct(
        west=west,
        south=south,
        east=east,
        north=north,
        resolution=resolution,
        afai=acc,
        coverage=coverage,
        lon=lon_c,
        lat=lat_c,
        times=times,
        used_wavelengths=used,
        files=[str(s.path.name) for s in swaths],
    )


def rgb_preview(swath: SwathAFAI, p_low: float = 2, p_high: float = 98) -> np.ndarray:
    if swath.rgb is None:
        raise ValueError("El swath no incluye RGB.")
    bands = []
    for band in swath.rgb:
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            bands.append(np.zeros(band.shape, dtype=np.float32))
            continue
        lo, hi = np.percentile(finite, [p_low, p_high])
        stretched = np.clip((band - lo) / max(hi - lo, 1e-6), 0, 1)
        bands.append(np.nan_to_num(stretched, nan=0.0))
    rgb = np.dstack(bands)
    return (rgb * 255).astype(np.uint8)


def save_grid(product: GridProduct, path: Path) -> None:
    np.savez_compressed(
        path,
        west=product.west,
        south=product.south,
        east=product.east,
        north=product.north,
        resolution=product.resolution,
        afai=product.afai,
        coverage=product.coverage,
        lon=product.lon,
        lat=product.lat,
        times=np.array(product.times, dtype=object),
        used_wavelengths=np.array(product.used_wavelengths),
        files=np.array(product.files, dtype=object),
    )


def load_grid(path: Path) -> GridProduct:
    data = np.load(path, allow_pickle=True)
    return GridProduct(
        west=float(data["west"]),
        south=float(data["south"]),
        east=float(data["east"]),
        north=float(data["north"]),
        resolution=float(data["resolution"]),
        afai=data["afai"],
        coverage=data["coverage"],
        lon=data["lon"],
        lat=data["lat"],
        times=list(data["times"]),
        used_wavelengths=tuple(float(x) for x in data["used_wavelengths"]),
        files=list(data["files"]),
    )


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def smooth_afai(grid: np.ndarray, sigma: float = 0.6) -> np.ndarray:
    filled = np.nan_to_num(grid, nan=0.0)
    return gaussian_filter(filled, sigma=sigma)
