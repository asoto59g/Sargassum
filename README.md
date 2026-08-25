# Sargazo Caribe

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

App Streamlit y CLI para **revisar manchas de sargazo flotante** en el mar Caribe con **NASA PACE OCI** (últimos días, casi tiempo real).

Calcula el índice **AFAI** sobre reflectancia de superficie (`rhos`, producto L2 SFREFL), recorta tierra con una máscara geográfica y exporta manchas (GeoJSON / CSV).

> AFAI señala material flotante. No es una clasificación definitiva de especie ni un aviso operativo de arribo a costa.

## Requisitos

- Windows, macOS o Linux
- **Python 3.11** (recomendado; 3.14 puede no tener ruedas de `netCDF4` / `scipy`)
- Cuenta [NASA Earthdata](https://urs.earthdata.nasa.gov/)
- Varios GB libres: cada granulo SFREFL pesa **~150–750 MB**

## Instalación

```bash
git clone https://github.com/asoto59g/Sargassum.git
cd Sargassum

python3.11 -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

En Windows, si `python` apunta a 3.14:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso: app web

```bash
streamlit run app.py
```

En Windows también puedes usar `run.bat`.

1. Abre [http://localhost:8501](http://localhost:8501).
2. En la barra lateral inicia sesión con tu usuario y contraseña Earthdata (se guarda en `_netrc` / `.netrc`, **nunca en el repo**).
3. Elige región (Mar Caribe, Caribe Costa Rica o Gran Caribe + Golfo), días y umbral AFAI.
4. Pulsa **Buscar y procesar PACE SFREFL**.

La primera corrida sobre todo el Caribe puede bajar varios granulos. Para probar, usa **Caribe Costa Rica** y 1–2 días.

Pestañas:

| Pestaña | Función |
| --- | --- |
| Últimos días | Busca, descarga y procesa SFREFL NRT / refinado |
| Archivos locales | Inspecciona `.nc` en `data/` (rechaza OC_AOP) |
| Por qué fallaba GEE | Limitaciones del prototipo `Sargaso_Caribe.js` |

## Uso: línea de comandos

```bash
# Inspeccionar NetCDF ya descargados
python -m sargazo --inspeccionar

# Buscar, descargar y detectar (requiere Earthdata)
python -m sargazo --dias 3 --region "Mar Caribe"

# Solo archivos locales SFREFL en data/
python -m sargazo --local --umbral 0.001 --min-pixeles 3
```

Regiones: `Mar Caribe`, `Caribe Costa Rica`, `Gran Caribe + Golfo`.

Salidas en `salidas/`: grilla AFAI (`.npz`), manchas (`.geojson`, `.csv`).

## Producto NASA correcto

| Usar | No usar |
| --- | --- |
| `PACE_OCI_L2_SFREFL_NRT` y `PACE_OCI_L2_SFREFL` | `PACE_OCI_L2_AOP` / `OC_AOP` |

El Rrs de OC_AOP llega ~**719 nm**. AFAI necesita **667 / 748 / 869 nm**, presentes en SFREFL (`rhos`). Detalle en [`docs/METODOLOGIA.md`](docs/METODOLOGIA.md).

## Estructura

```
app.py                 # Interfaz Streamlit
sargazo/               # Búsqueda Earthdata, AFAI, manchas
data/                  # Granulos .nc (gitignored)
salidas/               # GeoJSON / CSV / npz (gitignored)
Sargaso_Caribe.js      # Prototipo GEE no operativo
.streamlit/config.toml # Tema de la app
```

## Credenciales

No subas contraseñas. Opciones:

- Formulario de la app (`persist=True` → `_netrc` en Windows)
- Variables `EARTHDATA_USERNAME` y `EARTHDATA_PASSWORD`
- Archivo `.netrc` / `_netrc` en el home del usuario

`.gitignore` ya excluye `.netrc`, `_netrc`, `.env` y `.streamlit/secrets.toml`.

## Qué no va al repositorio

Los `.nc` de `data/` **no se commitean** (cientos de MB cada uno). Quien clone el repo debe autenticarse en Earthdata y dejar que la app los baje, o copiar granulos SFREFL a `data/`.

Comprueba antes del primer push:

```bash
git status
# No deben aparecer *.nc ni .venv
```

## Licencia

Este proyecto se distribuye bajo la [licencia MIT](LICENSE). El código es de uso libre; los granulos PACE siguen las [condiciones de NASA Earthdata](https://www.earthdata.nasa.gov/engage/open-data-services-and-software/data-and-information-policy).

Repositorio: <https://github.com/asoto59g/Sargassum>

## Limitaciones

- Falsos positivos por nubes, sunglint y costa.
- Resolución ~1.2 km (no sustituye Sentinel-2 cerca de playa).
- PACE no está en el catálogo público de Google Earth Engine.
- Umbrales AFAI son de partida; hay que revisarlos visualmente.

## Referencias

- Hu, C. (2009). A novel ocean color index to detect floating algae in the global oceans.
- [NASA PACE](https://pace.oceansciences.org/) · [Earthdata](https://www.earthdata.nasa.gov/) · [OB.DAAC](https://oceancolor.gsfc.nasa.gov/)
- [NASA Worldview](https://worldview.earthdata.nasa.gov/) · [USF SaWS](https://optics.marine.usf.edu/projects/saws.html)
- Método interno: [`docs/METODOLOGIA.md`](docs/METODOLOGIA.md)
