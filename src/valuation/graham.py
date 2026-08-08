"""
Benjamin Graham's two classic "defensive investor" valuation formulas.
Both are pure functions of EPS/BVPS/growth - no discount-rate assumption
needed for the Graham Number, which is what makes it the cheapest sanity
check to run before touching DCF/DDM (those need a discount rate you have
to pick yourself; this one doesn't).

Run this file directly to compute both for a real symbol (VNM) and compare
against its current price - see the __main__ block.
"""

import math

from market_access.price_access import get_company_overview
from valuation._inputs import EPS, EQUITY, open_session, ttm_flow, latest_snapshot


def graham_number(eps: float, bvps: float) -> float:
    """sqrt(22.5 x EPS x BVPS). 22.5 = Graham's ceiling of P/E 15 x P/B 1.5
    multiplied together - a stock priced above this is, by Graham's original
    "defensive investor" rule, expensive on both counts at once. Only
    meaningful when eps > 0 and bvps > 0; a loss-making or negative-equity
    company doesn't have a Graham Number, it just fails the screen."""
    if eps <= 0 or bvps <= 0:
        raise ValueError(f"Graham Number undefined for eps={eps}, bvps={bvps} (both must be > 0)")
    return math.sqrt(22.5 * eps * bvps)


def graham_growth_value(eps: float, growth_pct: float, aaa_yield_pct: float, base_yield_pct: float = 4.4) -> float:
    """Graham's later, growth-adjusted formula: V = EPS x (8.5 + 2g) x Y0/Y
    where g is expected annual EPS growth in whole percent (e.g. 8 for 8%),
    Y is the current AAA corporate bond yield in whole percent, and Y0=4.4%
    is the AAA yield at the time Graham calibrated the formula (1962) - the
    Y0/Y term rescales the P/E multiple for the present interest-rate
    environment instead of using 1962's. You have to supply a real current
    AAA (or closest local equivalent) yield; there's no sensible library
    default for this in a country whose bond market vnstock doesn't cover."""
    if aaa_yield_pct <= 0:
        raise ValueError("aaa_yield_pct must be > 0")
    return eps * (8.5 + 2 * growth_pct) * (base_yield_pct / aaa_yield_pct)


def for_symbol(symbol: str) -> dict:
    """Pulls TTM EPS + latest BVPS for `symbol` from the local DB/price
    access and returns the Graham Number alongside the inputs used, so the
    caller can see exactly what went into it. Growth-adjusted value isn't
    included here since it needs a growth rate + bond yield you have to
    choose - call graham_growth_value directly once you have those."""
    with open_session() as session:
        eps_ttm = ttm_flow(symbol, EPS, session)
        equity = latest_snapshot(symbol, EQUITY, session)
    overview = get_company_overview(symbol)
    shares = float(overview["issue_share"].iloc[0])
    price = float(overview["current_price"].iloc[0])
    bvps = equity / shares
    return {
        "symbol": symbol,
        "eps_ttm": eps_ttm,
        "bvps": bvps,
        "shares": shares,
        "current_price": price,
        "graham_number": graham_number(eps_ttm, bvps),
    }


if __name__ == "__main__":
    result = for_symbol("VNM")
    print("=== Graham Number for VNM ===")
    for k, v in result.items():
        print(f"{k}: {v:,.2f}" if isinstance(v, float) else f"{k}: {v}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs Graham Number "
        f"{result['graham_number']:,.0f} -> "
        f"{'above' if result['current_price'] > result['graham_number'] else 'at/below'} "
        "Graham's defensive-investor ceiling"
    )

    print("\n=== Graham growth formula, hand-check with known inputs ===")
    # Textbook check: EPS=2, g=0%, Y=4.4% (=Y0) should collapse to Graham's
    # original no-growth P/E-of-8.5 multiple, i.e. V = 8.5 * EPS.
    v = graham_growth_value(eps=2.0, growth_pct=0.0, aaa_yield_pct=4.4)
    print(f"EPS=2, g=0%, Y=4.4% -> V={v} (expected 17.0 = 8.5 x 2)")
    assert v == 17.0, "growth-adjusted formula should reduce to 8.5x EPS when g=0 and Y=Y0"
