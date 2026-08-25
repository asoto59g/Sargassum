from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sargazo.afai import (
    can_compute_afai,
    describe_nc,
    grid_swaths,
    read_swath_afai,
    rgb_preview,
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
from sargazo.earthdata import (
    download_granules,
    is_logged_in,
    local_nc_files,
    login,
    logout,
    search_last_days,
)
from sargazo.patches import extract_patches, patches_to_geojson, patches_to_rows

st.set_page_config(
    page_title="Sargazo Caribe",
    page_icon=":material/water:",
    layout="wide",
)

if "earthdata_ok" not in st.session_state:
    st.session_state.earthdata_ok = False
if "product" not in st.session_state:
    st.session_state.product = None
if "swaths" not in st.session_state:
    st.session_state.swaths = []
if "skipped" not in st.session_state:
    st.session_state.skipped = []


def _logged_in() -> bool:
    return bool(st.session_state.earthdata_ok) or is_logged_in()


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    west, south, east, north = bbox
    return (south + north) / 2, (west + east) / 2


@st.cache_data(ttl="1h", show_spinner=False)
def _describe(path_str: str, mtime: float) -> dict:
    meta = describe_nc(Path(path_str))
    return {
        "name": Path(path_str).name,
        "product": meta.product,
        "title": meta.title,
        "time_start": meta.time_start,
        "lat_min": meta.lat_min,
        "lat_max": meta.lat_max,
        "lon_min": meta.lon_min,
        "lon_max": meta.lon_max,
        "wmin": min(meta.wavelengths) if meta.wavelengths else None,
        "wmax": max(meta.wavelengths) if meta.wavelengths else None,
        "notes": meta.notes,
        "ok_afai": can_compute_afai(Path(path_str))[0],
        "reason": can_compute_afai(Path(path_str))[1],
        "covers": meta.intersects_bbox(REGIONES["Mar Caribe"]),
    }


def map_figure(
    product,
    patches,
    threshold: float,
    bbox,
    vista: str = "Ambas",
) -> go.Figure:
    mask = np.isfinite(product.afai) & (product.afai >= threshold)
    lat_c, lon_c = _bbox_center(bbox)
    fig = go.Figure()
    show_afai = vista in ("Señal AFAI", "Ambas")
    show_patches = vista in ("Manchas", "Ambas")

    if show_afai and mask.any():
        rows, cols = np.where(mask)
        lats = product.lat[rows]
        lons = product.lon[cols]
        vals = product.afai[mask]
        if vals.size > 40000:
            rng = np.random.default_rng(0)
            idx = rng.choice(vals.size, 40000, replace=False)
            lats, lons, vals = lats[idx], lons[idx], vals[idx]
        zmax = max(float(np.nanpercentile(vals, 98)), threshold * 2)
        fig.add_trace(
            go.Densitymap(
                lat=lats,
                lon=lons,
                z=vals,
                radius=16,
                colorscale=[
                    [0.0, "rgba(255,255,204,0)"],
                    [0.15, "rgba(255,237,160,0.35)"],
                    [0.4, "rgba(254,178,76,0.7)"],
                    [0.7, "rgba(240,59,32,0.85)"],
                    [1.0, "rgba(153,0,0,0.95)"],
                ],
                zmin=threshold,
                zmax=zmax,
                opacity=0.72,
                name="Señal AFAI",
                colorbar={"title": "AFAI", "len": 0.6},
                hovertemplate="AFAI=%{z:.4f}<br>%{lat:.3f}, %{lon:.3f}<extra></extra>",
            )
        )

    if show_patches and patches:
        for patch in patches[:60]:
            xs = [pt[0] for pt in patch.hull]
            ys = [pt[1] for pt in patch.hull]
            fig.add_trace(
                go.Scattermap(
                    lat=ys,
                    lon=xs,
                    mode="lines",
                    line={"color": "#C43C17", "width": 3},
                    name=f"Mancha {patch.id}",
                    showlegend=False,
                    hoverinfo="skip",
                    below="",
                )
            )
        fig.add_trace(
            go.Scattermap(
                lat=[p.lat for p in patches],
                lon=[p.lon for p in patches],
                mode="text",
                text=[str(p.id) for p in patches],
                textfont={"size": 13, "color": "#1A1A1A"},
                marker={"size": 0, "opacity": 0},
                name="Manchas",
                hovertemplate=(
                    "Mancha %{text}<br>%{customdata[0]:.1f} km²"
                    "<br>%{lat:.3f}, %{lon:.3f}<extra></extra>"
                ),
                customdata=[[p.area_km2] for p in patches],
                below="",
            )
        )

    fig.update_layout(
        map_style="carto-positron",
        map={"center": {"lat": lat_c, "lon": lon_c}, "zoom": 4.3},
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=620,
        paper_bgcolor="rgba(0,0,0,0)",
        legend={"bgcolor": "rgba(11,29,54,0.7)"},
    )
    return fig


def process_paths(paths: list[Path], bbox, mask_land_flag: bool):
    usable = []
    skipped = []
    for path in paths:
        ok, reason = can_compute_afai(path)
        if ok:
            usable.append(path)
        else:
            skipped.append((path.name, reason))
    if not usable:
        return None, skipped, []
    swaths = []
    for path in usable:
        swaths.append(
            read_swath_afai(
                path,
                bbox=bbox,
                mask_land_flag=mask_land_flag,
                include_rgb=True,
            )
        )
    return grid_swaths(swaths, bbox), skipped, swaths


with st.sidebar:
    st.markdown("### :material/water: Sargazo Caribe")
    st.caption("PACE OCI · AFAI · NASA Earthdata")
    region = st.selectbox("Región", list(REGIONES), index=0)
    bbox = REGIONES[region]
    days = st.slider("Días a revisar", 1, 10, DEFAULT_DAYS)
    max_granules = st.slider("Máximo de granulos", 1, 20, MAX_GRANULES_DEFAULT)
    threshold = st.slider(
        "Umbral AFAI",
        min_value=0.0002,
        max_value=0.008,
        value=DEFAULT_AFAI_THRESHOLD,
        step=0.0001,
        format="%.4f",
    )
    min_pixels = st.slider("Mínimo de píxeles por mancha", 1, 20, DEFAULT_MIN_PIXELS)
    mask_land_flag = st.toggle(
        "Enmascarar flag LAND",
        value=True,
        help="Si se pierden balsas reales cerca de costa, desactívalo. La máscara geográfica sigue activa.",
    )
    st.divider()
    st.markdown("**NASA Earthdata**")
    if _logged_in():
        st.badge("Sesión lista", icon=":material/check_circle:", color="green")
        st.session_state.earthdata_ok = True
        if st.button(
            ":material/logout: Cerrar sesión",
            width="stretch",
            help="Quita la sesión de esta app y las credenciales guardadas en _netrc.",
        ):
            logout()
            st.session_state.earthdata_ok = False
            st.rerun()
    else:
        with st.form("earthdata_login"):
            user = st.text_input("Usuario Earthdata")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Iniciar sesión", width="stretch")
            if submitted:
                try:
                    login(user, password, persist=True)
                    st.session_state.earthdata_ok = True
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo iniciar sesión: {exc}")
    st.caption(
        "Producto: PACE OCI L2 SFREFL (`rhos` 667 / 748 / 869 nm). "
        "OC_AOP no sirve para AFAI."
    )
    st.markdown(
        ":material/public: [Worldview](https://worldview.earthdata.nasa.gov/) · "
        "[SaWS USF](https://optics.marine.usf.edu/projects/saws.html)"
    )

st.title("Manchas de sargazo")
st.caption(
    "Revisión automática de los últimos días con PACE/OCI. "
    "AFAI indica material flotante; no es una clasificación definitiva de especie."
)

tabs = st.tabs(
    [
        ":material/satellite_alt: Últimos días",
        ":material/folder: Archivos locales",
        ":material/info: Por qué fallaba GEE",
    ],
    on_change="rerun",
)

with tabs[0]:
    if tabs[0].open:
        with st.container(horizontal=True):
            run = st.button(
                ":material/search: Buscar y procesar PACE SFREFL",
                type="primary",
            )
            st.info(
                f"{region}: lon {bbox[0]} a {bbox[2]}, lat {bbox[1]} a {bbox[3]}. "
                "Cada granulo SFREFL suele pesar 150–400 MB."
            )
        if run:
            if not _logged_in():
                st.error("Inicia sesión de NASA Earthdata en la barra lateral.")
            else:
                try:
                    with st.status("Buscando granulos PACE SFREFL…", expanded=True) as status:
                        granules = search_last_days(
                            bbox, days, max_granules=max_granules
                        )
                        if not granules:
                            status.update(
                                label="Sin granulos SFREFL para esa ventana",
                                state="error",
                            )
                        else:
                            st.dataframe(
                                pd.DataFrame(
                                    [
                                        {
                                            "granulo": g.name,
                                            "inicio": g.start.isoformat()
                                            if g.start
                                            else "",
                                            "MB": round(g.size_mb, 1)
                                            if g.size_mb
                                            else None,
                                        }
                                        for g in granules
                                    ]
                                ),
                                width="stretch",
                                hide_index=True,
                            )
                            status.update(label="Descargando…")
                            paths = download_granules(
                                granules, progress=lambda msg: status.write(msg)
                            )
                            status.update(label="Calculando AFAI…")
                            product, skipped, swaths = process_paths(
                                paths, bbox, mask_land_flag
                            )
                            st.session_state.product = product
                            st.session_state.swaths = swaths
                            st.session_state.skipped = skipped
                            status.update(label="Procesamiento listo", state="complete")
                except Exception as exc:
                    st.exception(exc)

with tabs[1]:
    if tabs[1].open:
        files = local_nc_files()
        if not files:
            st.write(f"No hay NetCDF en `{DATA_DIR}`.")
        else:
            rows = []
            for path in files:
                info = _describe(str(path), path.stat().st_mtime)
                cover = info["covers"]
                if cover is True:
                    cover_txt = "sí"
                elif cover is False:
                    cover_txt = "no"
                else:
                    cover_txt = "?"
                rows.append(
                    {
                        "archivo": info["name"],
                        "AFAI": "sí" if info["ok_afai"] else "no",
                        "Caribe": cover_txt,
                        "inicio": info["time_start"],
                        "lambda min": info["wmin"],
                        "lambda max": info["wmax"],
                        "nota": (info["notes"][0] if info["notes"] else info["reason"]),
                    }
                )
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            chosen = st.multiselect(
                "Procesar archivos SFREFL",
                [p.name for p in files if can_compute_afai(p)[0]],
            )
            if st.button("Procesar selección", width="stretch") and chosen:
                with st.status("Procesando archivos locales…", expanded=True):
                    paths = [DATA_DIR / name for name in chosen]
                    product, skipped, swaths = process_paths(
                        paths, bbox, mask_land_flag
                    )
                    st.session_state.product = product
                    st.session_state.swaths = swaths
                    st.session_state.skipped = skipped
        for name, reason in st.session_state.skipped:
            st.warning(f"{name}: {reason}")

with tabs[2]:
    if tabs[2].open:
        st.markdown(
            """
El script `Sargaso_Caribe.js` no puede funcionar tal cual en Google Earth Engine.

1. **PACE no está en el catálogo público de GEE.** El asset
   `projects/ee-TU_USUARIO/assets/PACE_OCI_CARIBE` es un marcador.
2. **OC_AOP no tiene las bandas AFAI.** El Rrs de PACE solo llega ~719 nm.
   Las bandas 748 y 869 nm están en **SFREFL (`rhos`)**.
3. **El archivo que descargaste** (`…20260815T010331…OC_AOP…`) cubre el **Pacífico**
   (lon ~165°), no el Caribe, y es de madrugada UTC.
4. **La máscara de océano era un rectángulo**, así que el raster cubría tierra.
5. **`reduceToVectors` de todo el Caribe a 300 m** suele agotar la cuota de GEE.

Esta app descarga SFREFL con tu cuenta Earthdata, calcula AFAI, recorta tierra
con una máscara geográfica y lista manchas de los últimos días.
"""
        )

product = st.session_state.product
if product is None:
    st.stop()

patches = extract_patches(product, threshold=threshold, min_pixels=min_pixels)
area = sum(p.area_km2 for p in patches)
n_cov = int((product.coverage > 0).sum())

with st.container(horizontal=True):
    st.metric("Manchas", f"{len(patches)}", border=True)
    st.metric("Área detectada", f"{area:.1f} km²", border=True)
    st.metric("Celdas con dato", f"{n_cov:,}", border=True)
    st.metric(
        "Bandas AFAI",
        " / ".join(f"{w:.0f} nm" for w in product.used_wavelengths),
        border=True,
    )

if product.files:
    st.caption("Granulos: " + " · ".join(product.files))

vista = st.segmented_control(
    "Vista del mapa",
    options=["Manchas", "Señal AFAI", "Ambas"],
    default="Ambas",
    help="La señal AFAI se muestra como mapa de calor. Los contornos son manchas agrupadas.",
)
st.plotly_chart(
    map_figure(product, patches, threshold, bbox, vista=vista or "Ambas"),
    width="stretch",
)
st.caption(
    "Naranja–rojo: señal AFAI (posible material flotante). "
    "Contorno e índice: mancha agrupada. "
    "Elige **Manchas** si solo quieres los polígonos, sin el mapa de calor."
)

left, right = st.columns([1.25, 1])
with left:
    st.subheader("Manchas")
    rows = patches_to_rows(patches)
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No hay manchas sobre el umbral. Baja el umbral AFAI o revisa nubes.")
with right:
    st.subheader("Exportar")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    st.download_button(
        ":material/download: GeoJSON de manchas",
        data=json.dumps(patches_to_geojson(patches), indent=2),
        file_name=f"manchas_sargazo_{stamp}.geojson",
        mime="application/geo+json",
        width="stretch",
    )
    if rows:
        st.download_button(
            ":material/download: CSV de manchas",
            data=pd.DataFrame(rows).to_csv(index=False),
            file_name=f"manchas_sargazo_{stamp}.csv",
            mime="text/csv",
            width="stretch",
        )
    if st.button(":material/save: Guardar grilla AFAI", width="stretch"):
        out = SALIDAS_DIR / f"afai_{stamp}.npz"
        save_grid(product, out)
        st.success(f"Guardado {out.name}")

swaths = st.session_state.swaths or []
if swaths:
    with st.expander("Vista RGB del granulo (control visual)"):
        labels = [s.path.name for s in swaths]
        pick = st.selectbox("Granulo", labels)
        swath = next(s for s in swaths if s.path.name == pick)
        try:
            st.image(
                rgb_preview(swath),
                caption=f"RGB ~665/560/443 nm · {swath.time_start}",
            )
        except Exception as exc:
            st.write(str(exc))
