"""
Relative valuation ("comps") - value a stock as what the market currently
pays for similar companies, via average peer P/E and P/B multiples applied
to the target's own EPS/BVPS. The odd one out among these four models: it
needs no discount-rate assumption at all, but needs a peer group - which
peers actually belong together is a judgement call the caller makes, not
something this module infers (no sector-similarity scoring exists yet).

Run this file directly to compute it for VNM against two real F&B peers.
"""

from market_access.financial_report import init_financial_history
from market_access.price_access import get_company_overview
from valuation._inputs import EPS, EQUITY, latest_snapshot, open_session, ttm_flow


def peer_average_multiple(prices: list[float], per_share_metrics: list[float]) -> float:
    """Average of price/metric across peers (e.g. price/EPS for P/E,
    price/BVPS for P/B). Peers with a non-positive metric are excluded - a
    negative P/E or P/B from a loss-making/negative-equity peer isn't a
    valuation multiple, it's noise."""
    ratios = [p / m for p, m in zip(prices, per_share_metrics) if m > 0]
    if not ratios:
        raise ValueError("no peer had a positive metric to compute a multiple from")
    return sum(ratios) / len(ratios)


def implied_value(multiple: float, target_metric: float) -> float:
    return multiple * target_metric


def _metrics_for(symbol: str) -> dict:
    """EPS (TTM), BVPS (latest), and current price for one symbol - loads
    the symbol's statement history first if it isn't in the DB yet (costs 3
    API calls, once per symbol ever)."""
    with open_session() as session:
        try:
            eps_ttm = ttm_flow(symbol, EPS, session)
            equity = latest_snapshot(symbol, EQUITY, session)
        except ValueError:
            session.close()
            init_financial_history(symbol)
            with open_session() as session2:
                eps_ttm = ttm_flow(symbol, EPS, session2)
                equity = latest_snapshot(symbol, EQUITY, session2)
    overview = get_company_overview(symbol)
    shares = float(overview["issue_share"].iloc[0])
    price = float(overview["current_price"].iloc[0])
    return {"price": price, "eps_ttm": eps_ttm, "bvps": equity / shares}


def for_symbol(symbol: str, peer_symbols: list[str]) -> dict:
    target = _metrics_for(symbol)
    peers = [_metrics_for(p) for p in peer_symbols]

    peer_pe = peer_average_multiple([p["price"] for p in peers], [p["eps_ttm"] for p in peers])
    peer_pb = peer_average_multiple([p["price"] for p in peers], [p["bvps"] for p in peers])

    return {
        "symbol": symbol,
        "peer_symbols": peer_symbols,
        "current_price": target["price"],
        "target_eps_ttm": target["eps_ttm"],
        "target_bvps": target["bvps"],
        "peer_avg_pe": peer_pe,
        "peer_avg_pb": peer_pb,
        "implied_value_pe": implied_value(peer_pe, target["eps_ttm"]),
        "implied_value_pb": implied_value(peer_pb, target["bvps"]),
    }


if __name__ == "__main__":
    print("=== Peer multiple, hand-check with known inputs ===")
    # Two peers priced at 10x and 20x their EPS -> average P/E should be 15.
    pe = peer_average_multiple(prices=[100, 200], per_share_metrics=[10, 10])
    print(f"prices=[100,200], eps=[10,10] -> avg P/E={pe} (expected 15.0)")
    assert pe == 15.0

    print("\n=== Relative valuation for VNM vs SAB, QNS (real F&B peers) ===")
    result = for_symbol("VNM", ["SAB", "QNS"])
    for k, v in result.items():
        print(f"{k}: {v:,.2f}" if isinstance(v, float) else f"{k}: {v}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs implied-by-P/E "
        f"{result['implied_value_pe']:,.0f}, implied-by-P/B {result['implied_value_pb']:,.0f}"
    )
