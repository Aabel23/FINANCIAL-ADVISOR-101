"""
Classical OLS regression diagnostics - the checklist a fitted model has to
pass before its coefficients mean what a plain reading of them suggests:
multicollinearity (VIF), heteroscedasticity (Breusch-Pagan), non-normal
residuals (Jarque-Bera), autocorrelation (Durbin-Watson), and influential
outliers (Cook's distance / studentized residuals). All hand-built on top
of regression.ols.fit() - same "own the model, don't call statsmodels"
convention as everywhere else in this project (see
docs/SYSTEM_OVERVIEW.md 3.2).

Durbin-Watson needs a caveat used nowhere else here: it tests whether
*consecutive* residuals (in whatever order the data is given) are
correlated - meaningful for time series, where "consecutive" means
"adjacent in time". model_builder.py's regression is cross-sectional (one
row per company, no natural time order), so a DW result there isn't really
testing anything real unless the rows happen to be sorted by something
informative. Computed and reported anyway (it was explicitly asked for),
but flagged, not auto-remediated the way the other four are.
"""

import numpy as np
from scipy import stats

from regression.ols import OLSResult, fit


def vif(x: dict[str, list[float]]) -> dict[str, float]:
    """Variance Inflation Factor per variable: regress that variable on
    every other variable in x, VIF = 1/(1-R²) of that auxiliary
    regression. VIF=1 means uncorrelated with the rest; conventionally >5
    is "worth a look", >10 is "this variable is redundant"."""
    names = list(x.keys())
    result = {}
    for name in names:
        others = {k: v for k, v in x.items() if k != name}
        if not others:
            result[name] = 1.0
            continue
        aux = fit(others, x[name])
        r2 = aux.r_squared
        result[name] = float("inf") if r2 >= 1.0 else 1 / (1 - r2)
    return result


def breusch_pagan(x: dict[str, list[float]], residuals: np.ndarray) -> tuple[float, float]:
    """Heteroscedasticity test: regress squared residuals on the same X's,
    test statistic = n * R² of that auxiliary regression, chi2-distributed
    with (number of X's) degrees of freedom under the null of constant
    residual variance. Returns (statistic, p-value); p < 0.05 -> reject
    homoscedasticity."""
    n = len(residuals)
    aux = fit(x, list(residuals**2))
    stat = n * aux.r_squared
    df = len(x)
    p_value = 1 - stats.chi2.cdf(stat, df=df)
    return float(stat), float(p_value)


def jarque_bera(residuals: np.ndarray) -> tuple[float, float]:
    """Normality test from sample skewness S and excess kurtosis K:
    JB = n/6 x (S² + K²/4), chi2(2) under the null of normality. Returns
    (statistic, p-value); p < 0.05 -> reject normality."""
    n = len(residuals)
    mean = residuals.mean()
    m2 = np.mean((residuals - mean) ** 2)
    m3 = np.mean((residuals - mean) ** 3)
    m4 = np.mean((residuals - mean) ** 4)
    skew = m3 / m2**1.5
    excess_kurt = m4 / m2**2 - 3
    stat = n / 6 * (skew**2 + excess_kurt**2 / 4)
    p_value = 1 - stats.chi2.cdf(stat, df=2)
    return float(stat), float(p_value)


def durbin_watson(residuals: np.ndarray) -> float:
    """DW = sum((e_t - e_(t-1))^2) / sum(e_t^2), t=2..n. ~2 = no
    autocorrelation, <2 = positive, >2 = negative. See module docstring:
    only meaningful if `residuals` has a real order (time, not company
    name)."""
    diffs = np.diff(residuals)
    return float((diffs**2).sum() / (residuals**2).sum())


def cooks_distance(result: OLSResult) -> np.ndarray:
    """Cook's distance per observation: how much the fitted coefficients
    would move if that one observation were dropped, combining its
    residual size and its leverage (how unusual its X values are).
    Conventional flag: D_i > 4/n."""
    studentized_sq = (result.residuals**2) / (result.sigma2 * (1 - result.leverage))
    return studentized_sq * result.leverage / (result.k * (1 - result.leverage))


def studentized_residuals(result: OLSResult) -> np.ndarray:
    """Residual scaled by its own standard error (which shrinks as
    leverage grows) - flags points a plain residual plot would understate
    because they've also pulled the fitted line toward themselves.
    |value| > 2-3 is conventionally "worth inspecting"."""
    s = np.sqrt(result.sigma2)
    return result.residuals / (s * np.sqrt(1 - result.leverage))


if __name__ == "__main__":
    print("=== VIF, hand-check with known inputs ===")
    orthogonal = {"x1": [1, -1, 1, -1], "x2": [1, 1, -1, -1]}
    v = vif(orthogonal)
    print(f"orthogonal x1,x2 -> VIF={v}")
    for name, val in v.items():
        assert abs(val - 1.0) < 1e-8, f"orthogonal variables should have VIF=1, got {name}={val}"

    collinear = {"x1": [1, 2, 3, 4], "x2": [2, 4, 6, 8]}  # x2 = 2*x1 exactly
    v2 = vif(collinear)
    print(f"x2=2*x1 (perfectly collinear) -> VIF={v2} (expect very large/inf)")
    assert v2["x1"] > 1e6

    print("\n=== Breusch-Pagan, hand-check with a deliberately heteroscedastic case ===")
    x = {"x1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}
    residuals = np.sqrt(np.array(x["x1"]))  # squared residuals == x1 exactly -> aux R²=1
    stat, p = breusch_pagan(x, residuals)
    print(f"stat={stat:.4f}, p={p:.6f} (expect stat==n==6.0 exactly, p<0.05 - textbook heteroscedasticity)")
    assert stat == 6.0
    assert p < 0.05

    print("\n=== Jarque-Bera, hand-check with a symmetric small sample ===")
    residuals = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    stat, p = jarque_bera(residuals)
    # by hand: m2=2, m3=0 (symmetric->skew=0), m4=6.8 -> excess_kurt=6.8/4-3=-1.3
    # JB = 5/6 * (0**2 + (-1.3)**2/4) = 5/6 * 0.4225 = 0.3520833...
    expected = 5 / 6 * (0**2 + (-1.3) ** 2 / 4)
    print(f"symmetric [-2..2] -> stat={stat:.6f} (expect {expected:.6f} - skew=0 exactly)")
    assert abs(stat - expected) < 1e-9

    print("\n=== Durbin-Watson, hand-check with an alternating (negatively autocorrelated) case ===")
    dw = durbin_watson(np.array([1.0, -1.0, 1.0, -1.0]))
    print(f"alternating residuals -> DW={dw} (expected 3.0, > 2 = negative autocorrelation)")
    assert dw == 3.0

    print("\n=== Cook's distance / studentized residuals, hand-check with one obvious outlier ===")
    x = {"x1": [1.0, 2.0, 3.0, 4.0, 5.0, 20.0]}
    y = [2.0, 4.0, 6.0, 8.0, 10.0, 5.0]  # first 5 points are exactly y=2x, last point breaks the pattern hard
    result = fit(x, y)
    cooks_d = cooks_distance(result)
    stud = studentized_residuals(result)
    print(f"Cook's D per obs: {np.round(cooks_d, 3)}")
    print(f"studentized residuals per obs: {np.round(stud, 3)}")
    worst = int(np.argmax(cooks_d))
    print(f"largest Cook's D at index {worst} (expected 5, the deliberately broken last point)")
    assert worst == 5
