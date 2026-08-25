from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SALIDAS_DIR = ROOT / "salidas"

DATA_DIR.mkdir(exist_ok=True)
SALIDAS_DIR.mkdir(exist_ok=True)

# Bounding boxes: (oeste, sur, este, norte)
REGIONES: dict[str, tuple[float, float, float, float]] = {
    "Mar Caribe": (-89.0, 8.0, -58.0, 25.5),
    "Caribe Costa Rica": (-84.0, 8.0, -81.5, 11.5),
    "Gran Caribe + Golfo": (-98.0, 8.0, -58.0, 31.0),
}

# AFAI clásico (Hu 2009): 667, 748 y 869 nm.
AFAI_LAMBDAS = (667.0, 748.0, 869.0)

# Producto correcto para AFAI: reflectancia de superficie (incluye 748 y 869 nm).
# OC_AOP/Rrs de PACE solo llega ~719 nm y NO sirve para AFAI.
SFREFL_SHORT_NAMES = (
    "PACE_OCI_L2_SFREFL_NRT",
    "PACE_OCI_L2_SFREFL",
)

# Máscaras OBPG por defecto. LAND se aplica además de una máscara geográfica.
DEFAULT_FLAG_MASK = (
    "ATMFAIL",
    "CLDICE",
    "HIGLINT",
    "HILT",
    "HISOLZEN",
    "NAVFAIL",
)

GRID_RES_DEG = 0.012  # ~1.3 km, cercano a la resolución nativa de OCI L2
COAST_BUFFER_PX = 2
DEFAULT_AFAI_THRESHOLD = 0.001
DEFAULT_MIN_PIXELS = 3
DEFAULT_DAYS = 3
MAX_GRANULES_DEFAULT = 10
