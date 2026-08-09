"""
Residual Income Model (RIM) - single-stage. Values equity as book value
plus the present value of "residual income" (the profit earned above what
shareholders required, i.e. ROE in excess of the cost of equity, applied to
book value). Where DCF/DDM value the cash a company pays or generates, RIM
values the accounting profit it earns beyond its cost of capital - useful
precisely when dividends are small/erratic (ddm.py's D0 would be near
worthless) or cash flow is choppy, since it anchors on book value + net
income instead.

Single-stage formula (assumes ROE and book-value growth both stay constant
forever, so residual income itself grows at g perpetually - same
"perpetuity" structure as Gordon Growth in ddm.py, just applied to residual
income instead of dividends):

    V0 = BV0 + (ROE - r) x BV0 / (r - g)

Run this file directly to compute it for VNM against real data.
"""

from valuation._inputs import EQUITY, NET_INCOME, current_price, latest_snapshot, open_session, shares_outstanding, ttm_flow


def single_stage_value(bv0: float, roe: float, r: float, g: float) -> float:
    """bv0 = current book value per share. roe = return on equity (whole
    fraction). r = required return on equity. g = perpetual book-value
    growth rate. Requires r > g, same reasoning as Gordon Growth (ddm.py) -
    a growth rate at or above the discount rate makes the perpetuity term
    diverge."""
    if r <= g:
        raise ValueError(f"single_stage_value requires r > g, got r={r}, g={g}")
    return bv0 + (roe - r) * bv0 / (r - g)


def for_symbol(symbol: str, r: float, g: float) -> dict:
    """ROE computed as TTM net income / latest equity (both totals, so the
    ratio is scale-free) rather than EPS/BVPS - avoids a subtle mismatch if
    EPS's weighted-average share count drifted from the year-end share
    count BVPS uses."""
    with open_session() as session:
        net_income_ttm = ttm_flow(symbol, NET_INCOME, session)
        equity = latest_snapshot(symbol, EQUITY, session)
        shares = shares_outstanding(symbol, session)
        price = current_price(symbol, session)

    bvps = equity / shares
    roe = net_income_ttm / equity
    return {
        "symbol": symbol,
        "net_income_ttm": net_income_ttm,
        "equity": equity,
        "bvps": bvps,
        "roe": roe,
        "r": r,
        "g": g,
        "current_price": price,
        "intrinsic_value": single_stage_value(bvps, roe, r, g),
    }


if __name__ == "__main__":
    print("=== Single-stage RIM, hand-check with known inputs ===")
    # BV0=100, ROE=15%, r=12%, g=5% -> V0 = 100 + (0.15-0.12)*100/(0.12-0.05)
    v = single_stage_value(bv0=100, roe=0.15, r=0.12, g=0.05)
    expected = 100 + (0.15 - 0.12) * 100 / (0.12 - 0.05)
    print(f"bv0=100, roe=15%, r=12%, g=5% -> value={v} (expected {expected})")
    assert abs(v - expected) < 1e-9

    import sys

    # DB only - never touches vnstock. If a symbol isn't loaded yet, run
    # `python -m market_access.financial_report SYMBOL` and
    # `python -m market_access.price_access SYMBOL` first (see README.md).
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "VNM"
    print(f"\n=== RIM for {symbol} (r=13%, g=4% - illustrative, tune these yourself) ===")
    result = for_symbol(symbol, r=0.13, g=0.04)
    for k, v in result.items():
        print(f"{k}: {v:,.4f}" if isinstance(v, float) else f"{k}: {v}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs RIM value "
        f"{result['intrinsic_value']:,.0f}"
    )
