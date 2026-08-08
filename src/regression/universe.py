"""
Curated cross-sectional universe for the price-regression model (see
model_builder.py): ~36 non-financial, non-fund symbols spread across
different ICB sectors on purpose - a regression fit only on, say, real
estate names would learn real-estate-specific relationships and call them
general. Hand-picked (not randomly sampled) so every symbol is a real,
liquid, recognizable company - a random sample of ~2000 listed tickers
would pull in thin-data small caps that fail more often than they add
signal.

Excludes banks/brokers/insurers (is_financial_sector) for the same reason
market_access does everywhere else: their balance sheets don't have a
comparable current-assets/current-liabilities or debt structure, so ratios
like current_ratio or debt/equity aren't meaningful for them.
"""

from market_access.db import Symbol, engine
from market_access.financial_report import init_market_financials
from sqlalchemy.orm import Session

SYMBOLS = [
    # F&B / consumer staples
    "VNM", "SAB", "MSN", "QNS", "KDC",
    # Retail
    "MWG", "PNJ", "FRT", "DGW",
    # Real estate
    "VHM", "VIC", "NVL", "KDH", "DXG",
    # Materials / steel
    "HPG", "HSG", "NKG", "DRC", "BMP",
    # Technology
    "FPT",
    # Energy / utilities
    "GAS", "POW", "PLX",
    # Transport
    "VJC", "GMD",
    # Agriculture / fertilizer
    "HAG", "DPM", "DCM",
    # Construction
    "CTD", "HBC",
    # Textile
    "TNG", "TCM",
    # Seafood
    "VHC", "ANV",
    # Pharma
    "DHG", "IMP",
]


def ensure_loaded(symbols: list[str] | None = None) -> None:
    """Loads statement history for every symbol in `symbols` (default:
    SYMBOLS) that isn't in the DB yet. Safe/cheap to re-run - only symbols
    actually missing hit the API (init_financial_history is itself an
    upsert, but we skip the call entirely for symbols already present)."""
    symbols = symbols or SYMBOLS
    with Session(engine) as session:
        existing = {s.symbol for s in session.query(Symbol.symbol).filter(Symbol.symbol.in_(symbols))}
        # dim_symbol has all ~2000 listed tickers synced already (see
        # market_access.db.sync_symbol_dimension) - that's not what we're
        # checking. What matters is whether fact_statement_line has data.
        from market_access.db import StatementLine

        loaded = {
            r[0] for r in session.query(StatementLine.symbol).filter(StatementLine.symbol.in_(symbols)).distinct()
        }
    missing = [s for s in symbols if s not in loaded]
    print(f"{len(loaded)}/{len(symbols)} already loaded, fetching {len(missing)} (rate-limited, ~3 calls/symbol)")
    if missing:
        init_market_financials(missing)  # throttled + per-symbol error handling, see market_access/financial_report.py


if __name__ == "__main__":
    ensure_loaded()
