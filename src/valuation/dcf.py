"""
Two-stage DCF on Free Cash Flow to Equity (FCFE) - discounts an explicit
n-year forecast of FCFE growing at g1, then a Gordon Growth terminal value
for everything after that at g_terminal, both discounted at the cost of
equity r. FCFE (not FCFF) so the discount rate is cost of equity, not WACC,
and the result is straight to equity/per-share value - no separate step to
subtract out debt.

FCFE = Operating Cash Flow - CapEx + Net Borrowing, computed here from
already-signed cash-flow-statement line items (capex and loan repayment are
stored negative, loan proceeds positive - see valuation._inputs), so it's a
sum, not sign-juggling three separate subtractions.

Run this file directly to compute it for VNM against real data.
"""

from market_access.price_access import get_company_overview
from valuation._inputs import (
    CAPEX,
    LOAN_PROCEEDS,
    LOAN_REPAYMENT,
    OPERATING_CASH_FLOW,
    open_session,
    ttm_flow,
)


def fcfe_ttm(symbol: str) -> float:
    """Trailing-twelve-month FCFE (total, not per share) for `symbol`."""
    with open_session() as session:
        ocf = ttm_flow(symbol, OPERATING_CASH_FLOW, session)
        capex = ttm_flow(symbol, CAPEX, session)
        loan_in = ttm_flow(symbol, LOAN_PROCEEDS, session)
        loan_out = ttm_flow(symbol, LOAN_REPAYMENT, session)
    return ocf + capex + loan_in + loan_out


def two_stage_value(fcfe0: float, r: float, g1: float, years1: int, g_terminal: float) -> float:
    """fcfe0 = most recent FCFE (per share, or total - result is in the same
    unit). r = cost of equity (whole fraction). g1 = FCFE growth rate for
    the explicit years1-year forecast window. g_terminal = perpetual growth
    rate applied after that. Requires r > g_terminal for the same reason as
    Gordon Growth (ddm.py) - a terminal growth rate at or above the discount
    rate makes the terminal value diverge."""
    if r <= g_terminal:
        raise ValueError(f"two_stage_value requires r > g_terminal, got r={r}, g_terminal={g_terminal}")

    pv_explicit = 0.0
    fcfe_t = fcfe0
    for t in range(1, years1 + 1):
        fcfe_t = fcfe_t * (1 + g1)
        pv_explicit += fcfe_t / (1 + r) ** t

    terminal_value_at_n = fcfe_t * (1 + g_terminal) / (r - g_terminal)
    pv_terminal = terminal_value_at_n / (1 + r) ** years1

    return pv_explicit + pv_terminal


def for_symbol(symbol: str, r: float, g1: float, years1: int, g_terminal: float) -> dict:
    """Pulls TTM FCFE for `symbol`, converts to per-share, and applies the
    two-stage discount. r/g1/g_terminal are genuine assumptions you supply -
    no library default, same reasoning as ddm.for_symbol."""
    fcfe0_total = fcfe_ttm(symbol)
    overview = get_company_overview(symbol)
    shares = float(overview["issue_share"].iloc[0])
    price = float(overview["current_price"].iloc[0])
    fcfe0_per_share = fcfe0_total / shares
    return {
        "symbol": symbol,
        "fcfe0_total": fcfe0_total,
        "shares": shares,
        "fcfe0_per_share": fcfe0_per_share,
        "r": r,
        "g1": g1,
        "years1": years1,
        "g_terminal": g_terminal,
        "current_price": price,
        "intrinsic_value": two_stage_value(fcfe0_per_share, r, g1, years1, g_terminal),
    }


if __name__ == "__main__":
    print("=== Two-stage FCFE DCF, hand-check with known inputs ===")
    # Single-stage sanity check: years1=0 should collapse to plain Gordon
    # Growth on fcfe0 itself, i.e. V = fcfe0*(1+g)/(r-g).
    v = two_stage_value(fcfe0=10, r=0.10, g1=0.0, years1=0, g_terminal=0.05)
    expected = 10 * 1.05 / (0.10 - 0.05)
    print(f"fcfe0=10, years1=0, g_terminal=5%, r=10% -> value={v} (expected {expected})")
    assert abs(v - expected) < 1e-9

    print("\n=== FCFE DCF for VNM (r=13%, g1=6% for 5y, g_terminal=3% - illustrative) ===")
    result = for_symbol("VNM", r=0.13, g1=0.06, years1=5, g_terminal=0.03)
    for k, val in result.items():
        print(f"{k}: {val:,.2f}" if isinstance(val, float) else f"{k}: {val}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs DCF value "
        f"{result['intrinsic_value']:,.0f}"
    )
