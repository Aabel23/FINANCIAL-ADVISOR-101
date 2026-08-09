"""
Relative valuation ("comps") - value a stock as what the market currently
pays for similar companies, via average peer P/E and P/B multiples applied
to the target's own EPS/BVPS. The odd one out among these four models: it
needs no discount-rate assumption at all, but needs a peer group - which
peers actually belong together is a judgement call the caller makes, not
something this module infers (no sector-similarity scoring exists yet).

Run this file directly to compute it for VNM against two real F&B peers.
"""

from valuation._inputs import EPS, EQUITY, current_price, latest_snapshot, open_session, shares_outstanding, ttm_flow


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
    """EPS (TTM), BVPS (latest), and current price for one symbol. DB only -
    never touches vnstock; raises (via valuation._inputs) if `symbol` isn't
    loaded yet. Run `python -m market_access.financial_report SYMBOL` and
    `python -m market_access.price_access SYMBOL` first for any peer that
    isn't already in the DB."""
    with open_session() as session:
        eps_ttm = ttm_flow(symbol, EPS, session)
        equity = latest_snapshot(symbol, EQUITY, session)
        shares = shares_outstanding(symbol, session)
        price = current_price(symbol, session)
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

    import sys

    args = [a.upper() for a in sys.argv[1:]]
    symbol, peer_symbols = (args[0], args[1:]) if args else ("VNM", ["SAB", "QNS"])
    if not peer_symbols:
        raise SystemExit(f"usage: python -m valuation.relative SYMBOL PEER1 [PEER2 ...] (got symbol={symbol!r}, no peers)")

    print(f"\n=== Relative valuation for {symbol} vs {', '.join(peer_symbols)} ===")
    result = for_symbol(symbol, peer_symbols)
    for k, v in result.items():
        print(f"{k}: {v:,.2f}" if isinstance(v, float) else f"{k}: {v}")
    print(
        f"\ncurrent price {result['current_price']:,.0f} vs implied-by-P/E "
        f"{result['implied_value_pe']:,.0f}, implied-by-P/B {result['implied_value_pb']:,.0f}"
    )
