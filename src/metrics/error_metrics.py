"""
Forecast/valuation accuracy metrics - MSE, RMSE, MAE, MAPE. Pure functions
on two equal-length sequences (actual vs predicted); no I/O, no data source
of their own.

The natural next brick after valuation/ has more than one model: once
several models each give their own intrinsic-value estimate for the same
stock, these are how you score which one actually landed close to the real
price - see the real-data demo in __main__. Later, once the
Statistical/Time-Series Engine (AR/ARIMA/GARCH - not built yet, see
docs/NEXT_STEPS.md step 6) exists, the same four functions score its return
forecasts against what actually happened; nothing here is specific to
valuation models.
"""


def _check(actual: list[float], predicted: list[float]) -> None:
    if len(actual) != len(predicted):
        raise ValueError(f"actual and predicted must be the same length, got {len(actual)} vs {len(predicted)}")
    if len(actual) == 0:
        raise ValueError("actual/predicted must not be empty")


def mse(actual: list[float], predicted: list[float]) -> float:
    """Mean Squared Error: mean((actual-predicted)^2). Penalizes large
    errors disproportionately (squared) - one bad outlier estimate
    dominates the score more than MAE would let it."""
    _check(actual, predicted)
    return sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)


def rmse(actual: list[float], predicted: list[float]) -> float:
    """Root Mean Squared Error: sqrt(MSE). Same units as the original data
    (e.g. VND, not VND^2) - the number to actually compare against price
    magnitude."""
    return mse(actual, predicted) ** 0.5


def mae(actual: list[float], predicted: list[float]) -> float:
    """Mean Absolute Error: mean(|actual-predicted|). Treats every error
    linearly - more robust to one outlier estimate than RMSE, at the cost
    of not distinguishing "one huge miss" from "several medium misses" the
    way RMSE does."""
    _check(actual, predicted)
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def mape(actual: list[float], predicted: list[float]) -> float:
    """Mean Absolute Percentage Error: mean(|actual-predicted|/|actual|),
    as a fraction (x100 for %). Scale-free - the only one of these four
    that's meaningful when comparing accuracy across stocks priced very
    differently (a 10,000 VND miss means something different for a 20,000
    VND stock than a 200,000 VND one; MSE/RMSE/MAE don't know that, MAPE
    does). Undefined (raises) if any actual value is 0."""
    _check(actual, predicted)
    if any(a == 0 for a in actual):
        raise ValueError("mape undefined when an actual value is 0")
    return sum(abs((a - p) / a) for a, p in zip(actual, predicted)) / len(actual)


if __name__ == "__main__":
    print("=== Hand-check with known inputs ===")
    actual = [10, 20, 30]
    predicted = [12, 18, 33]
    # errors: 2, -2, 3 -> squared: 4, 4, 9 -> mean = 17/3
    print(f"mse={mse(actual, predicted)} (expected {17 / 3})")
    assert abs(mse(actual, predicted) - 17 / 3) < 1e-9
    print(f"rmse={rmse(actual, predicted)} (expected {(17 / 3) ** 0.5})")
    assert abs(rmse(actual, predicted) - (17 / 3) ** 0.5) < 1e-9
    # abs errors: 2, 2, 3 -> mean = 7/3
    print(f"mae={mae(actual, predicted)} (expected {7 / 3})")
    assert abs(mae(actual, predicted) - 7 / 3) < 1e-9
    # pct errors: 2/10, 2/20, 3/30 = .2, .1, .1 -> mean = .4/3
    print(f"mape={mape(actual, predicted)} (expected {0.4 / 3})")
    assert abs(mape(actual, predicted) - 0.4 / 3) < 1e-9

    print("\n=== Real demo: VNM's valuation-model outputs vs its current price ===")
    from valuation import dcf, ddm, graham, nav, relative, rim

    graham_result = graham.for_symbol("VNM")
    ddm_result = ddm.for_symbol("VNM", r=0.13, g=0.04)
    dcf_result = dcf.for_symbol("VNM", r=0.13, g1=0.06, years1=5, g_terminal=0.03)
    relative_result = relative.for_symbol("VNM", ["SAB", "QNS"])
    nav_result = nav.for_symbol("VNM")
    rim_result = rim.for_symbol("VNM", r=0.13, g=0.04)

    price = graham_result["current_price"]
    estimates = {
        "graham": graham_result["graham_number"],
        "ddm": ddm_result["intrinsic_value"],
        "dcf-fcfe": dcf_result["intrinsic_value"],
        "relative-pe": relative_result["implied_value_pe"],
        "relative-pb": relative_result["implied_value_pb"],
        "nav": nav_result["nav_per_share"],
        "rim": rim_result["intrinsic_value"],
    }

    for name, value in estimates.items():
        print(f"{name}: {value:,.0f} (actual {price:,.0f}, error {value - price:+,.0f})")

    actual_prices = [price] * len(estimates)
    predicted_values = list(estimates.values())
    print(f"\nacross all {len(estimates)} models:")
    print(f"MSE  = {mse(actual_prices, predicted_values):,.0f}")
    print(f"RMSE = {rmse(actual_prices, predicted_values):,.0f}")
    print(f"MAE  = {mae(actual_prices, predicted_values):,.0f}")
    print(f"MAPE = {mape(actual_prices, predicted_values) * 100:.1f}%")
