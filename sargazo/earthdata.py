from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import earthaccess

from sargazo.config import DATA_DIR, MAX_GRANULES_DEFAULT, SFREFL_SHORT_NAMES


ProgressFn = Callable[[str], None]


@dataclass
class GranuleInfo:
    name: str
    start: datetime | None
    size_mb: float | None
    links: list[str]
    item: object


def login(
    username: str | None = None,
    password: str | None = None,
    persist: bool = True,
) -> object:
    """Inicia sesión en NASA Earthdata. Prioriza usuario/clave, luego .netrc."""
    if username and password:
        os.environ["EARTHDATA_USERNAME"] = username
        os.environ["EARTHDATA_PASSWORD"] = password
        return earthaccess.login(strategy="environment", persist=persist)
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return earthaccess.login(strategy="environment", persist=persist)
    return earthaccess.login(strategy="netrc")


def is_logged_in() -> bool:
    try:
        auth = earthaccess.login(strategy="netrc")
        return bool(auth)
    except Exception:
        try:
            if os.environ.get("EARTHDATA_USERNAME") and os.environ.get(
                "EARTHDATA_PASSWORD"
            ):
                auth = earthaccess.login(strategy="environment")
                return bool(auth)
        except Exception:
            return False
    return False


def _granule_name(item: object) -> str:
    try:
        native = item["umm"].get("GranuleUR") or item["umm"].get("DataGranule", {}).get(
            "Identifiers", [{}]
        )
        if isinstance(native, str):
            return native
    except Exception:
        pass
    links = []
    try:
        links = item.data_links()
    except Exception:
        pass
    if links:
        return Path(links[0]).name
    return str(item)


def _granule_start(item: object) -> datetime | None:
    try:
        umm = item["umm"]
        begin = umm["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        return datetime.fromisoformat(begin.replace("Z", "+00:00"))
    except Exception:
        name = _granule_name(item)
        # PACE_OCI.YYYYMMDDTHHMMSS.L2....
        parts = name.split(".")
        if len(parts) >= 2:
            try:
                return datetime.strptime(parts[1], "%Y%m%dT%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return None
        return None


def _granule_size_mb(item: object) -> float | None:
    try:
        size = item.size()
        if size is None:
            return None
        return float(size)
    except Exception:
        return None


def search_sfrefl(
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
    max_granules: int = MAX_GRANULES_DEFAULT,
) -> list[GranuleInfo]:
    """Busca granulos PACE SFREFL (NRT + refinado) que intersectan el bbox."""
    kwargs = dict(
        short_name=list(SFREFL_SHORT_NAMES),
        bounding_box=bbox,
        temporal=(start.isoformat(), end.isoformat()),
        count=max_granules * 3,
    )
    results = earthaccess.search_data(day_night_flag="day", **kwargs)
    if not results:
        results = earthaccess.search_data(**kwargs)
    granules: list[GranuleInfo] = []
    seen: set[str] = set()
    for item in results:
        name = _granule_name(item)
        # Preferir el producto refinado si NRT y refinado coinciden en timestamp.
        key = ".".join(name.split(".")[:3])  # PACE_OCI.YYYYMMDDTHHMMSS.L2
        if key in seen and "NRT" in name:
            continue
        if key in seen:
            granules = [g for g in granules if not g.name.startswith(key)]
        seen.add(key)
        granules.append(
            GranuleInfo(
                name=name,
                start=_granule_start(item),
                size_mb=_granule_size_mb(item),
                links=list(item.data_links()) if hasattr(item, "data_links") else [],
                item=item,
            )
        )
        if len(granules) >= max_granules:
            break
    granules.sort(key=lambda g: g.start or datetime.min.replace(tzinfo=timezone.utc))
    return granules[:max_granules]


def search_last_days(
    bbox: tuple[float, float, float, float],
    days: int,
    max_granules: int = MAX_GRANULES_DEFAULT,
) -> list[GranuleInfo]:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = datetime.now(timezone.utc).date() - timedelta(days=days)
    return search_sfrefl(bbox, start, end, max_granules=max_granules)


def local_nc_files(folder: Path | None = None) -> list[Path]:
    folder = folder or DATA_DIR
    return sorted(folder.glob("*.nc"))


def download_granules(
    granules: Iterable[GranuleInfo],
    dest: Path | None = None,
    progress: ProgressFn | None = None,
) -> list[Path]:
    dest = dest or DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    items = []
    existing: list[Path] = []
    for granule in granules:
        target = dest / granule.name
        if target.exists() and target.stat().st_size > 10_000:
            existing.append(target)
            if progress:
                progress(f"Ya descargado: {granule.name}")
            continue
        # A veces el nombre local no coincide exactamente; buscar por timestamp.
        stamp = granule.name.split(".")[1] if "." in granule.name else ""
        matches = list(dest.glob(f"*{stamp}*SFREFL*.nc")) if stamp else []
        if matches:
            existing.append(matches[0])
            if progress:
                progress(f"Ya descargado: {matches[0].name}")
            continue
        items.append(granule.item)
    if not items:
        return existing
    if progress:
        progress(f"Descargando {len(items)} granulo(s) PACE SFREFL…")
    paths = earthaccess.download(items, local_path=str(dest))
    downloaded = [Path(p) for p in paths]
    return existing + downloaded
