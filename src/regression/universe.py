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
    """Loads statement history AND price/shares/dividend snapshot data for
    every symbol in `symbols` (default: SYMBOLS) that isn't in the DB yet -
    _features.py's _row_for needs both. Safe/cheap to re-run - only symbols
    actually missing hit the API (init_financial_history/
    init_symbol_market_data are themselves upserts, but we skip the call
    entirely for symbols already present)."""
    from market_access.db import Price, StatementLine
    from market_access.price_access import init_market_prices

    symbols = symbols or SYMBOLS
    with Session(engine) as session:
        # dim_symbol has all ~2000 listed tickers synced already (see
        # market_access.db.sync_symbol_dimension) - that's not what we're
        # checking. What matters is whether the fact tables have data.
        statements_loaded = {
            r[0] for r in session.query(StatementLine.symbol).filter(StatementLine.symbol.in_(symbols)).distinct()
        }
        prices_loaded = {r[0] for r in session.query(Price.symbol).filter(Price.symbol.in_(symbols)).distinct()}

    missing_statements = [s for s in symbols if s not in statements_loaded]
    missing_prices = [s for s in symbols if s not in prices_loaded]
    print(
        f"{len(statements_loaded)}/{len(symbols)} have statements (fetching {len(missing_statements)}), "
        f"{len(prices_loaded)}/{len(symbols)} have price data (fetching {len(missing_prices)})"
    )
    if missing_statements:
        init_market_financials(missing_statements)  # throttled, see market_access/financial_report.py
    if missing_prices:
        init_market_prices(missing_prices)  # throttled, see market_access/price_access.py


if __name__ == "__main__":
    import sys

    symbols = [s.upper() for s in sys.argv[1:]] or None
    ensure_loaded(symbols)
