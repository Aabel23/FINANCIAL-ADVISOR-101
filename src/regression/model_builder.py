"""
Orchestrates ols.py + diagnostics.py into the full model-selection loop
agreed on for this project (see docs/NEXT_STEPS.md, "Regression pipeline -
current state"): fit OLS on the 9 candidate variables from _features.py,
then diagnose and remediate until the model passes or there's nothing left
to fix:

  1. VIF (multicollinearity)   - drop the single worst offender (VIF>10),
                                  refit, repeat.
  2. p-value (significance)    - drop the single least significant variable
                                  (p>0.05), refit, repeat. This is the
                                  "chỉ lấy biến quan trọng" step - what
                                  survives steps 1+2 is the final variable
                                  set.
  3. Breusch-Pagan (heteroscedasticity) - doesn't change which variables
                                  are in the model; if it fails, standard
                                  errors/p-values are recomputed with a
                                  heteroscedasticity-robust (HC1) covariance
                                  matrix instead of the plain OLS one.
  4. Jarque-Bera (normality)   - if residuals on raw price fail normality,
                                  the whole pipeline (steps 1-3) is re-run
                                  with log(price) as Y instead - price
                                  regressions are classically right-skewed,
                                  this is the standard fix, not special-
                                  cased for this project. Whichever of
                                  raw/log passes more diagnostics is kept.
  5. Cook's distance (outliers) - drop the single worst-influence
                                  observation (D > 4/n), re-run steps 1-2 on
                                  the remaining rows, refit. Capped at a few
                                  removals so this can't delete its way to a
                                  good-looking fit.
  6. Durbin-Watson             - computed and reported, never used to
                                  remediate (see diagnostics.py: not
                                  meaningful for cross-sectional data
                                  without a real row order).

Run this file directly to build the model end to end on the real
36-symbol universe.
"""

import numpy as np
from scipy import stats

from regression._features import FEATURE_NAMES, build_dataset
from regression.diagnostics import breusch_pagan, cooks_distance, durbin_watson, jarque_bera, vif
from regression.ols import OLSResult, fit

VIF_THRESHOLD = 10.0
ALPHA = 0.05
MAX_OUTLIER_REMOVALS = 3


def robust_hc1(result: OLSResult) -> tuple[np.ndarray, np.ndarray]:
    """Heteroscedasticity-robust (HC1/White-Huber sandwich) standard errors
    + p-values for an already-fit OLSResult - uses each observation's own
    squared residual instead of assuming one shared variance, with the
    standard small-sample n/(n-k) correction. Doesn't change beta, only how
    much to trust it."""
    X = result.X
    xtx_inv = np.linalg.inv(X.T @ X)
    correction = result.n / result.df_resid
    meat = X.T @ np.diag(result.residuals**2 * correction) @ X
    cov_robust = xtx_inv @ meat @ xtx_inv
    se_robust = np.sqrt(np.diag(cov_robust))
    t_robust = result.beta / se_robust
    p_robust = 2 * (1 - stats.t.cdf(np.abs(t_robust), df=result.df_resid))
    return se_robust, p_robust


def _drop_worst_vif(x: dict[str, list[float]], threshold: float) -> tuple[dict, str | None]:
    if len(x) <= 1:
        return x, None
    v = vif(x)
    worst = max(v, key=v.get)
    if v[worst] > threshold:
        return {k: val for k, val in x.items() if k != worst}, worst
    return x, None


def _drop_worst_pvalue(x: dict[str, list[float]], y: list[float], alpha: float) -> tuple[dict, str | None]:
    if len(x) <= 1:
        return x, None
    result = fit(x, y)
    p_by_name = dict(zip(result.feature_names[1:], result.p_values[1:]))  # skip "const"
    worst = max(p_by_name, key=p_by_name.get)
    if p_by_name[worst] > alpha:
        return {k: val for k, val in x.items() if k != worst}, worst
    return x, None


def select_variables(x: dict[str, list[float]], y: list[float]) -> dict[str, list[float]]:
    """Backward elimination: fully resolve VIF first (a p-value computed
    under severe multicollinearity isn't trustworthy enough to decide what
    to drop next), then drop insignificant variables one at a time."""
    while True:
        x, dropped = _drop_worst_vif(x, VIF_THRESHOLD)
        if dropped is None:
            break
        print(f"    VIF: dropped {dropped!r} (> {VIF_THRESHOLD})")
    while True:
        x, dropped = _drop_worst_pvalue(x, y, ALPHA)
        if dropped is None:
            break
        print(f"    p-value: dropped {dropped!r} (> {ALPHA})")
    return x


def _diagnose(result: OLSResult) -> dict:
    bp_stat, bp_p = breusch_pagan({n: result.X[:, i].tolist() for i, n in enumerate(result.feature_names) if n != "const"}, result.residuals)
    jb_stat, jb_p = jarque_bera(result.residuals)
    dw = durbin_watson(result.residuals)
    return {"bp_stat": bp_stat, "bp_p": bp_p, "jb_stat": jb_stat, "jb_p": jb_p, "dw": dw}


def _fit_with_remediation(x: dict[str, list[float]], y: list[float], symbols: list[str]) -> dict:
    print("  step 1-2: variable selection (VIF then p-value)")
    x = select_variables(x, y)
    result = fit(x, y)

    print("  step 5: outlier remediation (Cook's distance)")
    removals = 0
    while removals < MAX_OUTLIER_REMOVALS:
        d = cooks_distance(result)
        threshold = 4 / result.n
        worst_idx = int(np.argmax(d))
        if d[worst_idx] <= threshold:
            break
        dropped_symbol = symbols[worst_idx]
        print(f"    Cook's D: dropping {dropped_symbol!r} (D={d[worst_idx]:.3f} > {threshold:.3f})")
        x = {k: [v for i, v in enumerate(vals) if i != worst_idx] for k, vals in x.items()}
        y = [v for i, v in enumerate(y) if i != worst_idx]
        symbols = [s for i, s in enumerate(symbols) if i != worst_idx]
        x = select_variables(x, y)  # re-check VIF/significance on the remaining rows
        result = fit(x, y)
        removals += 1

    diag = _diagnose(result)
    print(f"  Breusch-Pagan: stat={diag['bp_stat']:.3f} p={diag['bp_p']:.4f} "
          f"({'HETEROSCEDASTIC' if diag['bp_p'] < ALPHA else 'ok'})")
    print(f"  Jarque-Bera:   stat={diag['jb_stat']:.3f} p={diag['jb_p']:.4f} "
          f"({'NON-NORMAL' if diag['jb_p'] < ALPHA else 'ok'})")
    print(f"  Durbin-Watson: {diag['dw']:.3f} (cross-sectional caveat - see diagnostics.py)")

    se, p = result.se, result.p_values
    if diag["bp_p"] < ALPHA:
        print("  -> applying HC1 robust standard errors (heteroscedasticity detected)")
        se, p = robust_hc1(result)

    n_diagnostics_passed = int(diag["bp_p"] >= ALPHA) + int(diag["jb_p"] >= ALPHA)
    return {
        "result": result,
        "symbols": symbols,
        "diag": diag,
        "robust_se": se,
        "robust_p": p,
        "n_diagnostics_passed": n_diagnostics_passed,
    }


def build_model(df) -> dict:
    """Runs the full pipeline once with Y=price and once with Y=log(price)
    (step 4's remediation for non-normal residuals), returns whichever
    passes more diagnostics (Breusch-Pagan + Jarque-Bera; ties favor raw
    price since that's what was explicitly asked for)."""
    symbols = list(df.index)
    x_full = {name: df[name].tolist() for name in FEATURE_NAMES}

    print("\n### Y = price ###")
    raw = _fit_with_remediation(dict(x_full), df["price"].tolist(), list(symbols))
    raw["label"] = "price"

    print("\n### Y = log(price) (normality remediation candidate) ###")
    log_run = _fit_with_remediation(dict(x_full), list(np.log(df["price"])), list(symbols))
    log_run["label"] = "log(price)"

    chosen = raw if raw["n_diagnostics_passed"] >= log_run["n_diagnostics_passed"] else log_run
    other = log_run if chosen is raw else raw
    print(
        f"\n### Selected Y={chosen['label']} "
        f"({chosen['n_diagnostics_passed']}/2 diagnostics passed vs {other['n_diagnostics_passed']}/2 for Y={other['label']}) ###"
    )
    result = chosen["result"]
    print(result.summary())
    return chosen


if __name__ == "__main__":
    df = build_dataset()
    chosen = build_model(df)
    r = chosen["result"]
    print(f"\nFinal variables kept: {[f for f in r.feature_names if f != 'const']}")
    print(f"n={r.n}  R2={r.r_squared:.4f}  adj-R2={r.adj_r_squared:.4f}")
