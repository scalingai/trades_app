"""Hechos XBRL como series *point-in-time*.

La distinción central de todo este módulo:

    `end`   = a qué fecha corresponde la medición  (ej. acciones al 2026-03-16)
    `filed` = cuándo se hizo pública               (ej. presentado el 2026-03-16)

Un backtest que indexa por `end` tiene look-ahead metido: al 2026-01-15 el
mercado NO sabía el share count del 2026-03-16. **Todo acceso point-in-time
filtra por `filed`.** Es la regla que hace honesto al dataset entero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterator

from .client import fetch_json
from .tickers import cik10

_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Conceptos que nos interesan para estructura de papel y runway.
CONCEPT_SHARES = ("dei", "EntityCommonStockSharesOutstanding")
CONCEPT_CASH = (
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
)
CONCEPT_OPCF = (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),)


@dataclass(frozen=True, slots=True)
class Fact:
    end: date
    val: float
    form: str
    filed: date
    accn: str
    unit: str
    start: date | None = None

    @property
    def duration_days(self) -> int | None:
        if self.start is None:
            return None
        return (self.end - self.start).days


class Series:
    """Serie de hechos XBRL de un concepto, con acceso point-in-time."""

    def __init__(self, concept: str, facts: list[Fact]) -> None:
        self.concept = concept
        # Orden canónico: por fecha de conocimiento, después por fecha de medición.
        self.facts = sorted(facts, key=lambda f: (f.filed, f.end))

    def __len__(self) -> int:
        return len(self.facts)

    def __iter__(self) -> Iterator[Fact]:
        return iter(self.facts)

    def __bool__(self) -> bool:
        return bool(self.facts)

    def asof(self, when: date) -> Fact | None:
        """El hecho vigente en `when`: el de medición más reciente **ya publicado**.

        Entre los hechos con `filed <= when`, devuelve el de mayor `end`.
        Si hay restatements para el mismo `end`, gana el de `filed` más reciente.
        """
        known = [f for f in self.facts if f.filed <= when]
        if not known:
            return None
        return max(known, key=lambda f: (f.end, f.filed))

    def history(self, *, forms: tuple[str, ...] | None = None) -> list[Fact]:
        """Un hecho por `end`, quedándose con el reporte más reciente de cada uno.

        Sirve para reconstruir la trayectoria real (ej. share count trimestre a
        trimestre) sin duplicados por restatement.
        """
        best: dict[date, Fact] = {}
        for f in self.facts:
            if forms and f.form not in forms:
                continue
            prev = best.get(f.end)
            if prev is None or f.filed > prev.filed:
                best[f.end] = f
        return [best[k] for k in sorted(best)]


def _parse_units(concept: str, units: dict) -> list[Fact]:
    out: list[Fact] = []
    for unit, entries in units.items():
        for e in entries:
            # `filed` y `end` son obligatorios en la práctica, pero un fact sin
            # `filed` es inutilizable point-in-time: se descarta en vez de
            # inventarle una fecha.
            if not e.get("filed") or not e.get("end"):
                continue
            out.append(
                Fact(
                    end=date.fromisoformat(e["end"]),
                    val=float(e["val"]),
                    form=e.get("form", ""),
                    filed=date.fromisoformat(e["filed"]),
                    accn=e.get("accn", ""),
                    unit=unit,
                    start=date.fromisoformat(e["start"]) if e.get("start") else None,
                )
            )
    return out


class CompanyFacts:
    """Todos los hechos XBRL de una empresa (una sola llamada a la SEC)."""

    def __init__(self, cik: int, payload: dict) -> None:
        self.cik = cik
        self.entity_name: str = payload.get("entityName", "")
        self._facts: dict = payload.get("facts", {})

    @classmethod
    def load(cls, cik: int, *, cache_hours: float = 12.0) -> "CompanyFacts":
        payload = fetch_json(_FACTS_URL.format(cik=cik10(cik)), cache_hours=cache_hours)
        return cls(cik, payload)

    def series(self, taxonomy: str, tag: str) -> Series:
        units = self._facts.get(taxonomy, {}).get(tag, {}).get("units", {})
        return Series(f"{taxonomy}:{tag}", _parse_units(f"{taxonomy}:{tag}", units))

    def first_available(self, concepts: tuple[tuple[str, str], ...]) -> Series:
        """Primera serie no vacía de una lista de conceptos equivalentes.

        Las micro caps no son consistentes con qué tag usan para caja; probamos
        en orden de preferencia y nos quedamos con la primera que exista.
        """
        for taxonomy, tag in concepts:
            s = self.series(taxonomy, tag)
            if s:
                return s
        taxonomy, tag = concepts[0]
        return Series(f"{taxonomy}:{tag}", [])

    # --- atajos de los conceptos que usa structure.py ---

    def shares(self) -> Series:
        return self.series(*CONCEPT_SHARES)

    def cash(self) -> Series:
        return self.first_available(CONCEPT_CASH)

    def operating_cash_flow(self) -> Series:
        return self.first_available(CONCEPT_OPCF)
