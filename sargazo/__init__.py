"""Detección de sargazo flotante con PACE OCI (AFAI)."""

from sargazo.config import REGIONES
from sargazo.earthdata import is_logged_in, login, logout

__all__ = ["REGIONES", "login", "logout", "is_logged_in"]
