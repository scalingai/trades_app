"""Cliente de Massive (ex Polygon.io) — datos de precio.

Separado de `edgar/` a propósito: EDGAR es gratis y sin key, Massive tiene
límite de rate por plan. Mezclarlos escondería el costo de cada llamada.
"""

from .client import MassiveClient, MassiveError, NotAuthorized
from .store import BarStore

__all__ = ["MassiveClient", "MassiveError", "NotAuthorized", "BarStore"]
