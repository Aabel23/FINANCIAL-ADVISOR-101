"""
Runs all six valuation models (dcf, ddm, graham, nav, relative, rim) for one
symbol at once and ranks the results - the cross-model counterpart to each
individual module's own __main__ block, same relationship model_builder.py
has to ols.py/diagnostics.py in regression/.

Two "best" pointers, not one - they answer different questions and neither
alone is the answer:
  - highest margin of safety: which model says the market price is most
    wrong (cheapest relative to that model's own intrinsic value) - the
    classic value-investing read, but a single model can be an outlier for
    a bad reason (a model-specific assumption that doesn't hold for this
    stock), not just because it "found" mispricing.
  - closest to consensus: which single model's estimate sits nearest the
    panel's median - a proxy for "least idiosyncratic", not for "most
    correct".

Consensus distance and the panel-wide MAE/RMSE/MAPE reuse
metrics.error_metrics rather than re-deriving the same arithmetic - see that
module's docstring, which already names this exact use case ("once several
models each give their own intrinsic-value estimate ... these are how you
score which one actually landed close to the real price").

r/g are genuine assumptions you supply, same reasoning as every individual
model's own for_symbol() - no library default. Shared across DCF/DDM/RIM:
DCF's explicit-forecast growth g1 is set equal to g, and its terminal growth
g_terminal defaults to g/2 (a lower, more sustainable rate for the "forever
after" leg - same qualitative reasoning as picking any terminal growth below
the explicit-stage growth, just automated instead of hand-picked per run).
Pass g_terminal explicitly to override.

Peers are optional - Relative is skipped (not failed) if none are given,
since unlike r/g there's no reasonable shared default for a peer group (see
relative.py: "which peers actually belong together is a judgement call the
caller makes"). Likewise, any individual model can fail on its own terms
(Graham needs positive EPS/BVPS, NAV needs the balance sheet to satisfy the
accounting identity, ...) without taking the rest of the panel down with it -
each model call is isolated and a failure just shows up as that row's error.

Run this file directly to compute the full panel for a real symbol.
"""

from metrics.error_metrics import mae, mape, rmse
from valuation import dcf, ddm, graham, nav, relative, rim
from valuation._inputs import current_price, open_session


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def for_symbol(
    symbol: str,
    r: float,
    g: float,
    peer_symbols: list[str] | None = None,
    years1: int = 5,
    g_terminal: float | None = None,
) -> dict:
    """Runs every valuation model for `symbol` under one shared set of
    assumptions and returns the full panel plus two rankings (see module
    docstring). Raises only if every single model failed - a partial panel
    (some models failed, at least one didn't) is returned normally, with
    failures visible per-row in models[]["error"]."""
    if g_terminal is None:
        g_terminal = g / 2

    with open_session() as session:
        price = current_price(symbol, session)

    models = []

    def run(name: str, fn) -> None:
        try:
            models.append({"model": name, "value": fn(), "error": None})
        except Exception as e:
            models.append({"model": name, "value": None, "error": str(e)})

    run("dcf-fcfe", lambda: dcf.for_symbol(symbol, r=r, g1=g, years1=years1, g_terminal=g_terminal)["intrinsic_value"])
    run("ddm", lambda: ddm.for_symbol(symbol, r=r, g=g)["intrinsic_value"])
    run("graham", lambda: graham.for_symbol(symbol)["graham_number"])
    run("nav", lambda: nav.for_symbol(symbol)["nav_per_share"])
    run("rim", lambda: rim.for_symbol(symbol, r=r, g=g)["intrinsic_value"])

    if peer_symbols:
        try:
            rel = relative.for_symbol(symbol, peer_symbols)
            models.append({"model": "relative-pe", "value": rel["implied_value_pe"], "error": None})
            models.append({"model": "relative-pb", "value": rel["implied_value_pb"], "error": None})
        except Exception as e:
            models.append({"model": "relative-pe", "value": None, "error": str(e)})
            models.append({"model": "relative-pb", "value": None, "error": str(e)})
    else:
        skip = "skipped - no peer_symbols given"
        models.append({"model": "relative-pe", "value": None, "error": skip})
        models.append({"model": "relative-pb", "value": None, "error": skip})

    for m in models:
        m["margin_of_safety"] = (m["value"] - price) / price if m["value"] is not None else None

    ok = [m for m in models if m["value"] is not None]
    if not ok:
        raise ValueError(f"{symbol}: every valuation model failed - see each model's error above")

    values = [m["value"] for m in ok]
    consensus = _median(values)
    for m in ok:
        m["distance_from_consensus"] = abs(m["value"] - consensus)

    best_margin = max(ok, key=lambda m: m["margin_of_safety"])
    closest_to_consensus = min(ok, key=lambda m: m["distance_from_consensus"])

    panel_actual = [price] * len(ok)
    return {
        "symbol": symbol,
        "current_price": price,
        "r": r,
        "g": g,
        "years1": years1,
        "g_terminal": g_terminal,
        "peer_symbols": peer_symbols or [],
        "models": models,
        "n_ok": len(ok),
        "n_failed": len(models) - len(ok),
        "consensus_value": consensus,
        "best_margin_of_safety": best_margin,
        "closest_to_consensus": closest_to_consensus,
        "panel_mae": mae(panel_actual, values),
        "panel_rmse": rmse(panel_actual, values),
        "panel_mape": mape(panel_actual, values),
    }


if __name__ == "__main__":
    print("=== median() hand-check with known inputs ===")
    m = _median([10, 20, 30])
    print(f"median([10,20,30])={m} (expected 20)")
    assert m == 20
    m = _median([10, 20, 30, 40])
    print(f"median([10,20,30,40])={m} (expected 25.0)")
    assert m == 25.0

    import sys

    # DB only - never touches vnstock. If a symbol (or a peer) isn't loaded
    # yet, run `python -m market_access.financial_report SYMBOL` and
    # `python -m market_access.price_access SYMBOL` first (see README.md).
    args = sys.argv[1:]
    symbol = args[0].upper() if args else "VNM"
    r = float(args[1]) if len(args) > 1 else 0.13
    g = float(args[2]) if len(args) > 2 else 0.05
    peers = [a.upper() for a in args[3:]] if len(args) > 3 else ["SAB", "QNS"]

    print(f"\n=== Valuation panel for {symbol} (r={r:.0%}, g={g:.0%}, peers={peers or 'none'}) ===")
    result = for_symbol(symbol, r=r, g=g, peer_symbols=peers)

    print(f"current price: {result['current_price']:,.0f}\n")
    print(f"{'model':<14}{'value':>14}{'margin of safety':>20}")
    ranked = sorted(
        (row for row in result["models"] if row["value"] is not None),
        key=lambda row: row["margin_of_safety"],
        reverse=True,
    )
    for row in ranked:
        print(f"{row['model']:<14}{row['value']:>14,.0f}{row['margin_of_safety']:>19.1%}")
    for row in result["models"]:
        if row["value"] is None:
            print(f"{row['model']:<14}{'--':>14}  {row['error']}")

    print(f"\nconsensus (median) value: {result['consensus_value']:,.0f}")
    print(
        f"panel spread vs current price: MAE={result['panel_mae']:,.0f} "
        f"RMSE={result['panel_rmse']:,.0f} MAPE={result['panel_mape']:.1%}"
    )

    best = result["best_margin_of_safety"]
    print(f"\nbest margin of safety: {best['model']} at {best['value']:,.0f} ({best['margin_of_safety']:+.1%} vs price)")
    closest = result["closest_to_consensus"]
    print(f"closest to consensus:  {closest['model']} at {closest['value']:,.0f} (consensus {result['consensus_value']:,.0f})")

    tail = f", {result['n_failed']} failed" if result["n_failed"] else ""
    print(f"\n{result['n_ok']}/{result['n_ok'] + result['n_failed']} models produced a value{tail}")