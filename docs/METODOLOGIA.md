# Método AFAI (PACE OCI)

Este documento resume por qué la app usa **PACE OCI L2 SFREFL** y cómo se calculan las manchas. No sustituye una validación de campo.

## Índice espectral

AFAI (Alternative Floating Algae Index; Hu 2009) mide el exceso de reflectancia cerca de 748 nm respecto a una línea base entre ~667 nm y ~869 nm:

```
AFAI = R(λ2) − [ R(λ1) + (R(λ3) − R(λ1)) × (λ2 − λ1) / (λ3 − λ1) ]
```

con λ1 ≈ 667 nm, λ2 ≈ 748 nm, λ3 ≈ 869 nm.

En PACE se toma la banda más cercana de `rhos` (reflectancia de superficie) en el producto **L2 SFREFL**.

Umbral inicial en la app: **0.001**. Hay que calibrarlo con revisión visual (RGB del granulo y, si hace falta, [NASA Worldview](https://worldview.earthdata.nasa.gov/) o [SaWS USF](https://optics.marine.usf.edu/projects/saws.html)).

## Por qué SFREFL y no OC_AOP

| Producto | Variable | Rango espectral típico | ¿AFAI? |
| --- | --- | --- | --- |
| `PACE_OCI_L2_AOP` / `OC_AOP` | `Rrs` | ~346–719 nm | No. Faltan 748 y 869 nm. |
| `PACE_OCI_L2_SFREFL` / `_NRT` | `rhos` | VNIR + SWIR, incluye 667 / 747–749 / 865–870 nm | Sí. |

ChatGPT y el script de Google Earth Engine asumían bandas `Rrs_667`, `Rrs_748` y `Rrs_869`. Esas variables con esos nombres **no existen** en OC_AOP de PACE.

Además, AFAI clásico se calcula sobre reflectancia Rayleigh-corregida o de superficie, no sobre Rrs oceánico con corrección atmosférica completa. Las balsas brillantes en NIR a menudo fallan o se enmascaran en el procesamiento oceánico estándar.

## Máscaras

1. **Geográfica:** tierra según `global-land-mask`, con un margen costero (~2 celdas, ≈ 2–3 km) para manglares y playa.
2. **Calidad OBPG (`l2_flags`):** por defecto `ATMFAIL`, `CLDICE`, `HIGLINT`, `HILT`, `HISOLZEN`, `NAVFAIL`.
3. **Flag `LAND`:** opcional. Si se pierden balsas cerca de costa, desactívalo en la barra lateral. El sargazo puede parecer vegetación terrestre en NIR.

No uses NDWI/NDVI para separar mar y tierra: el sargazo eleva el NIR y se clasifica como tierra.

## Composición de varios días

Los swaths L2 no están en una malla regular. Se binnean a ~0.012° (~1.3 km, cercano a OCI L2) y se guarda el **máximo AFAI** por celda. Una mediana de varios días diluye manchas que se mueven.

## Manchas

Sobre el umbral se etiquetan componentes conexos. Se descartan regiones con menos píxeles que el mínimo (por defecto 3). El área usa el tamaño de celda en km² según la latitud. El contorno es el casco convexo de las celdas; es una envolvente, no el borde exacto de la balsa.

## Limitaciones

- Nubes, sunglint y costas generan falsos positivos.
- Resolución ~1.2 km: no resuelve líneas finas junto a playa (eso pediría Sentinel-2).
- PACE no está en el catálogo público de Google Earth Engine.
- El script `Sargaso_Caribe.js` es un prototipo GEE **no operativo**.

## Referencias

- Hu, C. (2009). A novel ocean color index to detect floating algae in the global oceans. *Remote Sensing of Environment*.
- NASA PACE / OB.DAAC, producto OCI L2 SFREFL.
- NASA Ocean Color Level-2 flags: <https://oceancolor.gsfc.nasa.gov/resources/atbd/ocl2flags/>
