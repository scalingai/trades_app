"""Capa 0 — ingesta determinística de SEC EDGAR. Sin LLM, sin juicio."""

from .structure import PaperStructure, build
from .tickers import cik_for, ticker_for

__all__ = ["PaperStructure", "build", "cik_for", "ticker_for"]
