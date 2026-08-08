"""
Hand-built Ordinary Least Squares (OLS) linear regression via the closed-form
normal equations (numpy linear algebra) - no statsmodels/sklearn at runtime,
same "own the model" convention as the rest of this project's statistical
work (see docs/SYSTEM_OVERVIEW.md section 3.2: numpy + scipy are the
foundation this project hand-builds on, not a shortcut to a ready-made
implementation). Unlike GARCH (planned, not built yet), OLS has an exact
closed-form solution - no numerical optimizer needed here.

beta_hat = (X'X)^-1 X'y (computed via np.linalg.lstsq for numerical
stability rather than literally inverting X'X to get beta itself - (X'X)^-1
is still formed explicitly afterward since standard errors and leverage
need it anyway).
"""

import numpy as np
from scipy import stats


class OLSResult:
    def __init__(self, feature_names: list[str], beta: np.ndarray, X: np.ndarray, y: np.ndarray):
        self.feature_names = feature_names  # ["const", ...independent variables]
        self.beta = beta
        self.X = X
        self.y = y
        self.n, self.k = X.shape

        self.y_hat = X @ beta
        self.residuals = y - self.y_hat
        self.rss = float(self.residuals @ self.residuals)
        self.df_resid = self.n - self.k
        if self.df_resid <= 0:
            raise ValueError(f"not enough observations: n={self.n}, k={self.k} (need n > k)")
        self.sigma2 = self.rss / self.df_resid

        xtx_inv = np.linalg.inv(X.T @ X)
        cov_beta = self.sigma2 * xtx_inv
        self.se = np.sqrt(np.diag(cov_beta))
        self.t_stats = self.beta / self.se
        self.p_values = 2 * (1 - stats.t.cdf(np.abs(self.t_stats), df=self.df_resid))

        tss = float(((y - y.mean()) ** 2).sum())
        self.tss = tss
        self.r_squared = 1 - self.rss / tss if tss > 0 else 1.0
        self.adj_r_squared = 1 - (1 - self.r_squared) * (self.n - 1) / self.df_resid

        # Hat-matrix diagonal (leverage): how much observation i's own y
        # value influences its own fitted value. Needed by diagnostics.py
        # (Cook's distance, studentized residuals) - computed once here so
        # every caller doesn't redo the (X'X)^-1 sandwich.
        self.leverage = np.einsum("ij,jk,ik->i", X, xtx_inv, X)

    def coef(self, name: str) -> float:
        return float(self.beta[self.feature_names.index(name)])

    def pvalue(self, name: str) -> float:
        return float(self.p_values[self.feature_names.index(name)])

    def summary(self) -> str:
        lines = [f"{'variable':<22}{'coef':>18}{'std err':>16}{'t':>10}{'p>|t|':>10}"]
        for name, b, se, t, p in zip(self.feature_names, self.beta, self.se, self.t_stats, self.p_values):
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            lines.append(f"{name:<22}{b:>18,.4f}{se:>16,.4f}{t:>10.2f}{p:>10.4f} {sig}")
        lines.append(f"\nn={self.n}  k={self.k}  R2={self.r_squared:.4f}  adj-R2={self.adj_r_squared:.4f}")
        return "\n".join(lines)


def fit(x: dict[str, list[float]], y: list[float]) -> OLSResult:
    """x: {variable_name: [values...]}, no intercept column - added
    automatically as 'const'. y: dependent variable, same length as every
    list in x."""
    feature_names = ["const"] + list(x.keys())
    n = len(y)
    columns = [np.ones(n)] + [np.asarray(v, dtype=float) for v in x.values()]
    X = np.column_stack(columns)
    y_arr = np.asarray(y, dtype=float)
    beta, *_ = np.linalg.lstsq(X, y_arr, rcond=None)
    return OLSResult(feature_names, beta, X, y_arr)


if __name__ == "__main__":
    print("=== OLS, hand-check against a known-exact linear relationship ===")
    # y = 5 + 2*x1 - 3*x2, zero noise -> OLS must recover [5, 2, -3] exactly
    # and R²=1 exactly (no approximation error possible with a consistent,
    # noiseless, overdetermined system).
    x1 = [1, 2, 3, 4, 5, 6, 7, 8]
    x2 = [2, 1, 4, 3, 6, 5, 8, 7]
    y = [5 + 2 * a - 3 * b for a, b in zip(x1, x2)]
    result = fit({"x1": x1, "x2": x2}, y)
    print(result.summary())
    expected = np.array([5.0, 2.0, -3.0])
    assert np.allclose(result.beta, expected, atol=1e-8), f"expected {expected}, got {result.beta}"
    assert abs(result.r_squared - 1.0) < 1e-8, "noiseless exact-fit data must give R²=1"
    print("beta == [5, 2, -3] exactly, R² == 1.0 - OK")
