"""
Builds the cross-sectional feature matrix for model_builder.py: one row per
symbol in regression.universe.SYMBOLS, 9 candidate independent variables
derived from the financial statements (reflecting financial health) plus
the dependent variable (current stock price).

Variable formulas, all computed from fact_statement_line via
valuation._inputs (TTM = sum of last 4 quarters for flow items,
latest-quarter snapshot for balance-sheet items - see that module for why):

  eps            TTM EPS (isa23 summed over 4 quarters - already per-share)
  bvps           latest equity / shares outstanding
  roe            TTM net income / latest equity
  roa            TTM net income / latest total assets
  net_margin     TTM net income / TTM revenue
  revenue_growth (TTM revenue - prior-year TTM revenue) / prior-year TTM revenue
  debt_equity    latest (short-term + long-term borrowings) / latest equity
  current_ratio  latest current assets / latest current liabilities
  log_market_cap log(market cap) - size control. Logged, not raw: market
                 cap spans orders of magnitude across this universe (small
                 caps to VIC/VHM), and log-size is the standard form this
                 control takes in cross-sectional equity regressions (same
                 reasoning as the Fama-French size factor) - a raw-VND
                 market cap column would just swamp everything else's
                 scale, not add information a linear model couldn't already
                 get from log of it.

Any symbol missing a value for any variable (division by zero, missing
line item, insufficient quarters) is dropped with a printed reason, not
silently imputed - a regression is only as trustworthy as the data that
went into it.
"""

import numpy as np
import pandas as pd

from regression.universe import SYMBOLS
from valuation._inputs import (
    CURRENT_ASSETS,
    CURRENT_LIABILITIES,
    EPS,
    EQUITY,
    LONG_TERM_DEBT,
    NET_INCOME,
    REVENUE,
    SHORT_TERM_DEBT,
    TOTAL_ASSETS,
    current_price,
    latest_snapshot,
    open_session,
    shares_outstanding,
    ttm_flow,
    ttm_flow_prior_year,
)

FEATURE_NAMES = [
    "eps",
    "bvps",
    "roe",
    "roa",
    "net_margin",
    "revenue_growth",
    "debt_equity",
    "current_ratio",
    "log_market_cap",
]


def _row_for(symbol: str, session) -> dict | None:
    try:
        eps_ttm = ttm_flow(symbol, EPS, session)
        net_income_ttm = ttm_flow(symbol, NET_INCOME, session)
        revenue_ttm = ttm_flow(symbol, REVENUE, session)
        revenue_ttm_prior = ttm_flow_prior_year(symbol, REVENUE, session)
        equity = latest_snapshot(symbol, EQUITY, session)
        total_assets = latest_snapshot(symbol, TOTAL_ASSETS, session)
        current_assets = latest_snapshot(symbol, CURRENT_ASSETS, session)
        current_liabilities = latest_snapshot(symbol, CURRENT_LIABILITIES, session)
        short_debt = latest_snapshot(symbol, SHORT_TERM_DEBT, session)
        long_debt = latest_snapshot(symbol, LONG_TERM_DEBT, session)
        shares = shares_outstanding(symbol, session)
        price = current_price(symbol, session)
    except ValueError as e:
        print(f"{symbol}: skipped - {e}")
        return None

    if equity <= 0 or revenue_ttm == 0 or current_liabilities == 0 or revenue_ttm_prior == 0 or total_assets == 0:
        print(f"{symbol}: skipped - non-positive/zero denominator in equity/revenue/current_liabilities/assets")
        return None

    market_cap = price * shares  # not stored separately - DB only keeps price and shares, this is derived
    if shares <= 0 or price <= 0:
        print(f"{symbol}: skipped - non-positive shares/price")
        return None

    return {
        "symbol": symbol,
        "price": price,
        "eps": eps_ttm,
        "bvps": equity / shares,
        "roe": net_income_ttm / equity,
        "roa": net_income_ttm / total_assets,
        "net_margin": net_income_ttm / revenue_ttm,
        "revenue_growth": (revenue_ttm - revenue_ttm_prior) / revenue_ttm_prior,
        "debt_equity": (short_debt + long_debt) / equity,
        "current_ratio": current_assets / current_liabilities,
        "log_market_cap": float(np.log(market_cap)),
    }


def build_dataset(symbols: list[str] | None = None) -> pd.DataFrame:
    symbols = symbols or SYMBOLS
    rows = []
    with open_session() as session:
        for symbol in symbols:
            row = _row_for(symbol, session)
            if row is not None:
                rows.append(row)
    df = pd.DataFrame(rows).set_index("symbol")
    print(f"\n{len(df)}/{len(symbols)} symbols kept after data-quality filtering")
    return df


if __name__ == "__main__":
    import sys

    # DB only - never touches vnstock. Missing symbols are skipped (with a
    # printed reason) by build_dataset, not auto-fetched. Run
    # `python -m regression.universe SYMBOL1 SYMBOL2 ...` first to backfill
    # any symbol that isn't in the DB yet.
    symbols = [s.upper() for s in sys.argv[1:]] or None
    print(f"=== Building the cross-sectional feature matrix ({'custom symbols' if symbols else 'default 36-symbol universe'}) ===")
    df = build_dataset(symbols)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(df)

    if "VNM" in df.index:
        print("\n=== Cross-check VNM's row against valuation/ modules' already-verified numbers ===")
        vnm = df.loc["VNM"]
        print(f"eps={vnm['eps']:,.0f} (expect 4,728 - matches graham.py's TTM EPS)")
        print(f"bvps={vnm['bvps']:,.1f} (expect ~17,065.6 - matches graham.py/nav.py)")
        print(f"roe={vnm['roe']:.4f} (expect ~0.3074 - matches rim.py)")
        assert abs(vnm["eps"] - 4728) < 1
        assert abs(vnm["bvps"] - 17065.6) < 1
        assert abs(vnm["roe"] - 0.3074) < 1e-3
