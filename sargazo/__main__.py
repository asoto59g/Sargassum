from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sargazo.afai import (
    can_compute_afai,
    describe_nc,
    grid_swaths,
    read_swath_afai,
    save_grid,
)
from sargazo.config import (
    DATA_DIR,
    DEFAULT_AFAI_THRESHOLD,
    DEFAULT_DAYS,
    DEFAULT_MIN_PIXELS,
    MAX_GRANULES_DEFAULT,
    REGIONES,
    SALIDAS_DIR,
)
from sargazo.earthdata import download_granules, local_nc_files, login, search_last_days
from sargazo.patches import extract_patches, patches_to_geojson, patches_to_rows


def _print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detecta manchas de sargazo (AFAI) con PACE OCI SFREFL."
    )
    parser.add_argument("--dias", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--region", choices=list(REGIONES), default="Mar Caribe")
    parser.add_argument("--umbral", type=float, default=DEFAULT_AFAI_THRESHOLD)
    parser.add_argument("--min-pixeles", type=int, default=DEFAULT_MIN_PIXELS)
    parser.add_argument("--max-granulos", type=int, default=MAX_GRANULES_DEFAULT)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Procesar solo archivos .nc ya descargados en data/",
    )
    parser.add_argument("--inspeccionar", action="store_true")
    args = parser.parse_args(argv)

    bbox = REGIONES[args.region]

    if args.inspeccionar:
        files = local_nc_files()
        if not files:
            _print(f"No hay .nc en {DATA_DIR}")
            return 1
        for path in files:
            meta = describe_nc(path)
            _print("=" * 60)
            _print(path.name)
            _print(f"Producto: {meta.product}")
            _print(f"Título:   {meta.title}")
            _print(f"Inicio:   {meta.time_start}")
            _print(
                f"Bbox:     lon {meta.lon_min}..{meta.lon_max}  "
                f"lat {meta.lat_min}..{meta.lat_max}"
            )
            if meta.wavelengths:
                _print(
                    f"bandas:   {min(meta.wavelengths):.0f}-{max(meta.wavelengths):.0f} nm "
                    f"({len(meta.wavelengths)} bandas)"
                )
            for note in meta.notes:
                _print(f"Nota:     {note}")
        return 0

    paths: list[Path]
    if args.local:
        paths = local_nc_files()
    else:
        _print("Iniciando sesión en NASA Earthdata…")
        login()
        _print(f"Buscando PACE SFREFL de los últimos {args.dias} días ({args.region})…")
        granules = search_last_days(bbox, args.dias, max_granules=args.max_granulos)
        if not granules:
            _print("No se encontraron granulos SFREFL para esa ventana.")
            return 1
        for g in granules:
            size = f"{g.size_mb:.0f} MB" if g.size_mb else "?"
            _print(f"  - {g.name}  ({size})")
        paths = download_granules(granules, progress=_print)

    usable = []
    for path in paths:
        ok, reason = can_compute_afai(path)
        if ok:
            usable.append(path)
        else:
            _print(f"Omitido {path.name}: {reason}")

    if not usable:
        _print(
            "No hay archivos SFREFL para AFAI. "
            "Descarga PACE_OCI_L2_SFREFL_NRT (no OC_AOP)."
        )
        return 1

    swaths = []
    for path in usable:
        _print(f"Calculando AFAI: {path.name}")
        swaths.append(read_swath_afai(path, bbox=bbox, include_rgb=False))

    product = grid_swaths(swaths, bbox)
    patches = extract_patches(product, threshold=args.umbral, min_pixels=args.min_pixeles)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    grid_path = SALIDAS_DIR / f"afai_{stamp}.npz"
    geo_path = SALIDAS_DIR / f"manchas_{stamp}.geojson"
    csv_path = SALIDAS_DIR / f"manchas_{stamp}.csv"
    save_grid(product, grid_path)
    geo_path.write_text(json.dumps(patches_to_geojson(patches), indent=2), encoding="utf-8")
    rows = patches_to_rows(patches)
    if rows:
        import pandas as pd

        pd.DataFrame(rows).to_csv(csv_path, index=False)

    area = sum(p.area_km2 for p in patches)
    _print(f"Manchas: {len(patches)}  |  Área total: {area:.1f} km²")
    _print(f"Salidas: {grid_path}")
    _print(f"         {geo_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
