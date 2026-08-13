"""Timeline de filings desde el endpoint de submissions.

Acá vive la taxonomía de qué form significa qué en términos de dilución.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from .client import fetch_json
from .tickers import cik10

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SUBMISSIONS_EXTRA = "https://data.sec.gov/submissions/{name}"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{doc}"

# --- taxonomía de dilución -------------------------------------------------
# `kind` agrupa forms en el evento económico que representan.

SHELF_FORMS = {"S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A"}
REGISTRATION_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A"}
EFFECT_FORMS = {"EFFECT"}
# 424B5 = prospectus supplement de un shelf (se está pricing algo AHORA).
# 424B3 = típicamente registro de reventa (converts tóxicos, overhang crónico).
PRICING_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "424B7"}
CURRENT_REPORT_FORMS = {"8-K", "8-K/A", "6-K"}
PERIODIC_FORMS = {"10-Q", "10-K", "10-K/A", "10-Q/A", "20-F"}
PROXY_FORMS = {"DEF 14A", "DEFA14A", "PRE 14A"}

# Items de 8-K que suelen acompañar dilución no registrada.
DILUTIVE_8K_ITEMS = {
    "1.01",  # entrada en acuerdo material (PIPE, securities purchase agreement)
    "3.02",  # venta no registrada de equity
    "3.03",  # modificación de derechos de tenedores
    "5.03",  # enmienda de estatutos (reverse split, aumento de autorizadas)
}


def classify(form: str) -> str:
    if form in SHELF_FORMS:
        return "shelf"
    if form in REGISTRATION_FORMS:
        return "registration"
    if form in EFFECT_FORMS:
        return "effect"
    if form in PRICING_FORMS:
        return "pricing"
    if form in CURRENT_REPORT_FORMS:
        return "current_report"
    if form in PERIODIC_FORMS:
        return "periodic"
    if form in PROXY_FORMS:
        return "proxy"
    return "other"


DILUTION_RELEVANT = {"shelf", "registration", "effect", "pricing"}


@dataclass(frozen=True, slots=True)
class Filing:
    accession: str
    form: str
    filed: date
    kind: str
    items: tuple[str, ...]
    primary_doc: str
    cik: int
    accepted_at: datetime | None = None

    @property
    def url(self) -> str:
        return _ARCHIVE.format(
            cik=self.cik,
            accn_nodash=self.accession.replace("-", ""),
            doc=self.primary_doc,
        )

    @property
    def is_dilution_relevant(self) -> bool:
        if self.kind in DILUTION_RELEVANT:
            return True
        # Un 8-K solo cuenta si trae un item dilutivo.
        return self.kind == "current_report" and bool(
            set(self.items) & DILUTIVE_8K_ITEMS
        )


def _rows(block: dict, cik: int) -> list[Filing]:
    """Convierte el formato de arrays paralelos de la SEC en objetos."""
    forms = block.get("form", [])
    out: list[Filing] = []
    for i, form in enumerate(forms):
        def col(name: str, default=""):
            arr = block.get(name, [])
            return arr[i] if i < len(arr) else default

        filed_raw = col("filingDate")
        if not filed_raw:
            continue
        accepted_raw = col("acceptanceDateTime")
        accepted = None
        if accepted_raw:
            try:
                accepted = datetime.fromisoformat(accepted_raw.replace("Z", "+00:00"))
            except ValueError:
                accepted = None
        items_raw = col("items") or ""
        out.append(
            Filing(
                accession=col("accessionNumber"),
                form=form,
                filed=date.fromisoformat(filed_raw),
                kind=classify(form),
                items=tuple(s.strip() for s in items_raw.split(",") if s.strip()),
                primary_doc=col("primaryDocument"),
                cik=cik,
                accepted_at=accepted,
            )
        )
    return out


def load_filings(cik: int, *, cache_hours: float = 12.0, full: bool = True) -> list[Filing]:
    """Timeline completo de filings, ordenado por fecha ascendente.

    `full=True` sigue los archivos paginados con el historial viejo. Para una
    micro cap con pocos años de historia suele venir todo en `recent`, pero un
    diluidor serial puede pasarse de las 1000 filas y perder justo lo viejo.
    """
    payload = fetch_json(_SUBMISSIONS_URL.format(cik=cik10(cik)), cache_hours=cache_hours)
    filings = payload.get("filings", {})
    out = _rows(filings.get("recent", {}), cik)

    if full:
        for extra in filings.get("files", []):
            name = extra.get("name")
            if not name:
                continue
            block = fetch_json(
                _SUBMISSIONS_EXTRA.format(name=name), cache_hours=24 * 7
            )
            out.extend(_rows(block, cik))

    out.sort(key=lambda f: (f.filed, f.accession))
    return out


def filter_filings(
    filings: Iterable[Filing],
    *,
    kinds: set[str] | None = None,
    forms: set[str] | None = None,
    since: date | None = None,
    until: date | None = None,
) -> list[Filing]:
    res = []
    for f in filings:
        if kinds and f.kind not in kinds:
            continue
        if forms and f.form not in forms:
            continue
        if since and f.filed < since:
            continue
        if until and f.filed > until:
            continue
        res.append(f)
    return res
