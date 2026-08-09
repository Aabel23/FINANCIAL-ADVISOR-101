"""
Net Asset Value (NAV) / asset-based valuation - the third leg of the
classic valuation triad alongside income-based (dcf.py, ddm.py, rim.py) and
market-based (relative.py) approaches: value a share as its accounting net
worth, not as a claim on future cash flows or what peers trade at.

NAV per share = (Total Assets - Total Liabilities) / Shares, computed here
from the two balance-sheet totals directly rather than reusing the Owner's
Equity line (bsa78) as-is - the two should be identical by the accounting
identity (Assets = Liabilities + Equity), so for_symbol() also doubles as a
live data-integrity check on the star schema: if a future symbol's loaded
statement data doesn't satisfy that identity, this raises instead of
silently returning a wrong number.

Run this file directly to compute it for VNM against real data.
"""

from valuation._inputs import (
    EQUITY,
    TOTAL_ASSETS,
    TOTAL_LIABILITIES,
    current_price,
    latest_snapshot,
    open_session,
    shares_outstanding,
)


def nav_per_share(total_assets: float, total_liabilities: float, shares: float) -> float:
    if shares <= 0:
        raise ValueError(f"shares must be > 0, got {shares}")
    return (total_assets - total_liabilities) / shares


def for_symbol(symbol: str) -> dict:
    with open_session() as session:
        assets = latest_snapshot(symbol, TOTAL_ASSETS, session)
        liabilities = latest_snapshot(symbol, TOTAL_LIABILITIES, session)
        equity_reported = latest_snapshot(symbol, EQUITY, session)
        shares = shares_outstanding(symbol, session)
        price = current_price(symbol, session)

    net_assets = assets - liabilities
    discrepancy = abs(net_assets - equity_reported)
    tolerance = abs(equity_reported) * 0.01  # 1% - statement rounding, not a real break
    if discrepancy > tolerance:
        raise ValueError(
            f"{symbol}: Assets-Liabilities ({net_assets:,.0f}) vs reported Equity "
            f"({equity_reported:,.0f}) differ by {discrepancy:,.0f}, more than 1% tolerance - "
            "check the loaded statement data before trusting this NAV figure"
        )

    return {
        "symbol": symbol,
        "total_assets": assets,
        "total_liabilities": liabilities,
        "net_assets": net_assets,
        "equity_reported": equity_reported,
        "shares": shares,
        "current_price": price,
        "nav_per_share": nav_per_share(assets, liabilities, shares),
    }


if __name__ == "__main__":
    print("=== NAV per share, hand-check with known inputs ===")
    v = nav_per_share(total_assets=1000, total_liabilities=400, shares=60)
    print(f"assets=1000, liabilities=400, shares=60 -> nav_per_share={v} (expected 10.0)")
    assert v == 10.0

    import sys

    # DB only - never touches vnstock. If a symbol isn't loaded yet, run
    # `python -m market_access.financial_report SYMBOL` and
    # `python -m market_access.price_access SYMBOL` first (see README.md).
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "VNM"
    print(f"\n=== NAV for {symbol} (also checks Assets-Liabilities == reported Equity) ===")
    result = for_symbol(symbol)
    for k, v in result.items():
        print(f"{k}: {v:,.2f}" if isinstance(v, float) else f"{k}: {v}")
    print(f"\ncurrent price {result['current_price']:,.0f} vs NAV {result['nav_per_share']:,.0f}")
