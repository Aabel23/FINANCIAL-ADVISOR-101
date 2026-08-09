"""
Dividend Discount Model - Gordon Growth (single-stage, constant perpetual
growth). The classic "value a stock as the dividend stream it pays you"
model; only sensible for steady, reliably-dividend-paying companies (VNM is
a textbook case - see __main__), not growth stocks that pay little/no
dividend.

Run this file directly to compute it for VNM against real data.
"""

from valuation._inputs import current_price, open_session, trailing_dividend_per_share


def gordon_growth_value(d0: float, r: float, g: float) -> float:
    """P0 = D1 / (r - g), D1 = D0 x (1+g). d0 = most recent trailing annual
    dividend per share, r = required return on equity (whole fraction, e.g.
    0.15 for 15%), g = expected perpetual dividend growth rate (whole
    fraction). Requires r > g - a growth rate at or above the discount rate
    makes the model diverge (infinite value), which is a sign g was picked
    too high, not a real result."""
    if r <= g:
        raise ValueError(f"gordon_growth_value requires r > g, got r={r}, g={g}")
    d1 = d0 * (1 + g)
    return d1 / (r - g)


def for_symbol(symbol: str, r: float, g: float) -> dict:
    """Pulls the latest trailing dividend-per-share for `symbol` from the
    local DB (dividend_per_share_tsr, refreshed by
    market_access.price_access.sync_company_snapshot) and applies Gordon
    Growth with the caller-supplied r/g - both are genuine assumptions
    (cost of equity, long-run growth) with no sensible library default, by
    design (see docs/SYSTEM_OVERVIEW.md: "the investment philosophy, made
    explicit and adjustable, instead of buried in a black box")."""
    with open_session() as session:
        d0 = trailing_dividend_per_share(symbol, session)
        price = current_price(symbol, session)
    return {
        "symbol": symbol,
        "d0": d0,
        "r": r,
        "g": g,
        "current_price": price,
        "intrinsic_value": gordon_growth_value(d0, r, g),
    }


if __name__ == "__main__":
    print("=== Gordon Growth DDM, hand-check with known inputs ===")
    # D0=10, r=10%, g=5% -> D1=10.5, P0 = 10.5 / 0.05 = 210
    v = gordon_growth_value(d0=10, r=0.10, g=0.05)
    print(f"d0=10, r=10%, g=5% -> value={v} (expected 210.0)")
    assert v == 210.0

    import sys

    # DB only - never touches vnstock. If a symbol isn't loaded yet, run
    # `python -m market_access.price_access SYMBOL` first (see README.md).
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "VNM"
    print(f"\n=== DDM for {symbol} (r=13%, g=4% - illustrative, tune these yourself) ===")
    result = for_symbol(symbol, r=0.13, g=0.04)
    for k, v in result.items():
        print(f"{k}: {v:,.2f}" if isinstance(v, float) else f"{k}: {v}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs DDM value "
        f"{result['intrinsic_value']:,.0f}"
    )
