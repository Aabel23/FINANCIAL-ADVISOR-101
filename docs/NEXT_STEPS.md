# Next Steps

## Where things actually stand right now

```
financial_tool/
  .venv/                          <- isolated Python 3.14 env, vnstock==4.0.2 + numpy/pandas/scipy/sqlalchemy
  pyproject.toml                  <- package "vnquant", sqlalchemy now a core dep (was api-extra only)
  data_cache/                      <- gitignored, per-day parquet cache written by price_access.py
  database/
    financial_reports.db            <- SQLite, gitignored (*.db), written by financial_report.py
  src/
    market_access/                  <- renamed from data_crawling/
      price_access.py                <- DONE: ticker listing, price history (normalized to raw VND),
                                         company overview, get_stock_universe() (market symbols minus
                                         investment funds, ~1871 of 2042 listed tickers). Day-cache only.
      db.py                           <- DONE: shared star-schema ORM (dim_symbol, dim_sector,
                                         dim_statement_item, dim_period, fact_statement_line) — see
                                         docs/DATA_MODEL.md, now implemented+verified, not just proposed.
      financial_report.py            <- DONE: quarterly balance sheet / income statement / cash flow
                                         for the whole market, persisted permanently to SQLite through
                                         db.py's schema (not a day-cache — see docs/DATA_MODEL.md)
  docs/
    SYSTEM_OVERVIEW.md              <- architecture + concepts reference (written before some of
                                       the structure changes below — folder names there are stale)
    DATA_MODEL.md                    <- dim/fact schema: design + verification, now implemented
    NEXT_STEPS.md                   <- this file
  README.md
```

Git: `financial_tool/` now has its **own standalone repo** (it was briefly absorbed into the
parent `AI101` repo, then split back out) pushed to `github.com/Aabel23/FINANCIAL-ADVISOR-101`
— that remote previously had unrelated history (3 commits, including one from a different
email) which was force-replaced after explicit confirmation. Current state: 1 commit, matches
everything below except the doc edits happening right now.

vnstock account: a free-tier API key is registered locally (`~/.vnstock/api_key.json`, outside the repo). This raised limits from guest (20 req/min, 4 statement periods/call) to free (**60 req/min, 3600/hour, 10000/day, 8 statement periods/call** — confirmed live, higher than originally assumed).

## Financial data model — see docs/DATA_MODEL.md

Implemented and verified as a small star schema (`dim_symbol`, `dim_sector`,
`dim_statement_item`, `dim_period`, `fact_statement_line`) instead of the original flat
`statement_lines` table — full reasoning, the two corrections made after checking real data
(no ICB parent-hierarchy in the data; `is_financial_sector` derived from `com_type_code` not
sector names), and the re-verification against real VNM/VCB data are all in that doc now, not
duplicated here. Still true from before: **history depth ceiling is 8 quarters** regardless of
`get_all` (confirmed live) — real depth only builds up over repeated `update_market_financials()`
calls, one quarter at a time, forever. **Not yet run at market scale** — only VNM has been
loaded end-to-end under the new schema. Running `init_market_financials()` for the full
~1871-symbol universe is still to do.

## Immediate next steps, in order

1. ~~Resolve the `src/vnquant/` leftover.~~ Deleted — superseded by `src/data_crawling/` (later renamed `src/market_access/`).
2. ~~First commit.~~ Done (now on the standalone `financial_tool/` repo, pushed to GitHub).
3. ~~Round out data crawling.~~ Done, then further split: price data stays in `price_access.py` (day-cache), financial statements moved to `financial_report.py` + `db.py` (permanent SQLite, star schema, whole-market scope) — see docs/DATA_MODEL.md. `Finance.ratio()` is still confirmed broken (empty output) in vnstock 4.0.2 regardless of period cap — ratios will be computed from the raw statements ourselves, not sourced from vnstock.
4. ~~`src/quant/` ratios + Piotroski score.~~ Superseded in practice by step 4b below: instead of a standalone ratios module, the individual valuation models each compute the specific ratios they need directly (EPS, BVPS, ROE, ROA, ... all live in `valuation/_inputs.py`). No separate Piotroski F-score has been built - still a real gap if a pure quality-screen number is wanted later, independent of the regression work in step 4c.
4b. **`src/valuation/` — DONE, 6 traditional valuation models, each standalone-runnable** (`python -m valuation.<name>`, verified against real VNM data):
   - `graham.py` — Graham Number + Graham's growth formula
   - `ddm.py` — Dividend Discount Model (Gordon Growth, single-stage)
   - `dcf.py` — DCF on FCFE, two-stage (explicit forecast + Gordon Growth terminal)
   - `nav.py` — Net Asset Value / asset-based (also double-checks Assets−Liabilities==Equity as a data-integrity check)
   - `rim.py` — Residual Income Model, single-stage
   - `relative.py` — P/E, P/B relative valuation against a caller-supplied peer list
   - `_inputs.py` — shared helper: TTM (sum of last 4 quarters) for flow items, latest-quarter snapshot for balance-sheet items, now also `ttm_flow_prior_year` (offset window) for YoY figures. **TTM-by-summing is deliberate** — confirmed live that vnstock's quarterly figures are discrete per-quarter, not YTD-cumulative.
   - `src/metrics/error_metrics.py` — DONE: `mse`/`rmse`/`mae`/`mape`, pure functions, no data source of their own. (Named `metrics/`, not `statistics/` — that name shadows Python's stdlib `statistics` module, confirmed live it breaks `-m` imports.) Demo scores all 6 valuation models above against VNM's current price.
5. **`src/regression/` — DONE, full pipeline built and run end-to-end on real data (2026-08-08), see "Regression pipeline — current state" below.** A cross-sectional OLS model: predict stock price from fundamental-statement variables, market-wide (not per-symbol like the valuation models above), with model-selection/diagnostic-driven variable pruning.
6. ~~`database/` folder's exact scope.~~ Settled: SQLite via SQLAlchemy, star schema (see DATA_MODEL.md), currently holds financial statement facts + symbol/sector/item/period dimensions. Whether a computed ranking run also lands here (as `fact_ranking`) or in a separate DB is still open.
7. **Statistical/time-series engine** (AR/ARIMA, GARCH, beta vs VN-Index) — original Step 6, still not started. Note the overlap with step 5: `metrics/error_metrics.py` and the diagnostic tests being built in `regression/diagnostics.py` (Durbin-Watson, Breusch-Pagan/heteroscedasticity, Jarque-Bera/normality) are exactly what AR/ARIMA residual checking needs too - build once in `regression/`, reuse here, don't re-derive.
8. **`main/` folder** — the local web host (FastAPI) + the entry point that loops over the universe. Threading/parallelism explicitly deferred until actually needed (GIL makes plain threading ineffective for the CPU-bound math anyway).
9. **`frontend/`** — React ranked table + stock detail page, last.

## Regression pipeline — current state (DONE, built + run 2026-08-08)

**Goal, agreed with you across a few rounds of back-and-forth** (see conversation, not reproduced in full here): a cross-sectional OLS regression, **Y = stock price**, **X = variables derived from the financial statements** that reflect financial health — used to inform buy/sell decisions. Explicitly **not** using `statsmodels`/`sklearn` at runtime for the regression or its diagnostics - hand-built on numpy/scipy, same convention as the rest of this project's statistical work (see SYSTEM_OVERVIEW.md 3.2). You flagged you want to discuss open questions before I just pick defaults - the design below is what we landed on together; anything not explicitly agreed is marked as such.

**Candidate X variables (9, all sourced from `fact_statement_line` + `price_access`)**: EPS (TTM), BVPS, ROE, ROA, net margin, revenue growth YoY, debt/equity (short+long borrowings / equity), current ratio, market cap (control for size). Not all 9 are expected to survive - see the selection/remediation loop below.

**Universe**: 36 hand-picked non-financial, multi-sector symbols (`regression/universe.py:SYMBOLS`) - not a random sample, so every symbol is a real, liquid, recognizable company spread across F&B, retail, real estate, materials, tech, energy, transport, agriculture, construction, textile, seafood, pharma. Banks/brokers/insurers excluded (same reasoning as everywhere else in this project - their statements aren't comparable on current_ratio/debt-equity).

**Model-selection / defect-remediation loop, agreed with you**: fit OLS with all surviving candidates -> check VIF (drop highest, refit, repeat while any VIF > ~10) -> check p-values (drop least significant, refit, repeat while any p > 0.05 - this is the "chỉ lấy biến quan trọng" step) -> check Breusch-Pagan (if heteroscedastic, switch to robust/HC1 standard errors, don't drop variables for this) -> check Jarque-Bera (if residuals non-normal, retry with log(price) as Y, since price-level regressions are classically right-skewed - keep whichever of raw/log Y passes more diagnostics) -> check Cook's distance (drop worst outlier observation, refit, up to a small cap so we don't just delete our way to a good-looking fit) -> Durbin-Watson is computed and reported but **not** auto-remediated and **not trusted** the way the other four are - it tests whether *consecutive* residuals correlate, which only means something if the rows have a real order (time), and this is cross-sectional (one row per company) - flagged explicitly in `diagnostics.py`'s docstring so this caveat isn't lost later.

**Built so far**:
- `valuation/_inputs.py` extended with `REVENUE`, `CURRENT_ASSETS`, `CURRENT_LIABILITIES`, `SHORT_TERM_DEBT`, `LONG_TERM_DEBT` item ids + `quarters_window(offset=...)` + `ttm_flow_prior_year` (for YoY).
- `regression/universe.py` — the 36-symbol list + `ensure_loaded()` (throttled via `market_access.financial_report.init_market_financials`, safe/cheap to re-run, only fetches symbols actually missing from `fact_statement_line`).
- `regression/ols.py` — hand-built OLS (`fit()` -> `OLSResult` with beta/SE/t/p/R²/adj-R²/leverage), hand-checked against a noiseless exact-linear synthetic case (recovers `[5, 2, -3]` and R²=1.0 exactly). **Run and verified.**

- `regression/diagnostics.py` — VIF, Breusch-Pagan, Jarque-Bera, Durbin-Watson, Cook's distance/studentized residuals, all on top of `ols.fit()`. Every function hand-checked against a deterministic known-answer case (e.g. perfectly collinear columns -> VIF→∞, alternating residuals -> DW==3.0 exactly). **Run and verified.**
- `regression/_features.py` — builds the 9-variable + price matrix for all 36 universe symbols. VNM's row cross-checked against `valuation/`'s already-verified numbers (EPS 4,728, BVPS 17,065.6, ROE 0.3074 - exact match). **Run and verified.**
- `regression/model_builder.py` — the orchestration loop described above, plus `robust_hc1()` (White/HC1 robust standard errors - the heteroscedasticity remediation). **Run and verified against the real 36-symbol universe.**

**Result of the real run** (`python -m regression.model_builder`): Y=price failed Breusch-Pagan (heteroscedastic, p=0.037) - pipeline auto-retried with Y=log(price) per the agreed remediation, which passed both Breusch-Pagan (p=0.84) and Jarque-Bera (p=0.33) and was selected (2/2 vs 1/2 diagnostics passed).

Final model: **log(price) ~ const + bvps + roa + net_margin + log_market_cap** (eps, roe, revenue_growth, debt_equity, current_ratio all eliminated - roe by VIF, the rest by insignificance), after removing 3 Cook's-distance outliers (VIC, CTD, VHC - named, not silently dropped). **n=33, R²=0.838, adj-R²=0.815**, every remaining coefficient significant at p<0.05.

**Worth a second look, not auto-resolved**: `net_margin`'s coefficient is **negative** (-1.39) - higher margin associated with lower log(price) once bvps/roa/log_market_cap are already in the model. Plausibly a real "controlling for size and returns, margin adds little else" effect, or a residual multicollinearity artifact from dropping `roe` - flagged rather than silently accepted, worth a second pass (different VIF threshold, alternative margin definition) before trusting this sign for real investment decisions.

**Open follow-ups, none started**:
- No out-of-sample backtest - R²=0.838 is in-sample fit on the same 36 rows the model was built from, says nothing about predicting a 37th company correctly.
- `studentized_residuals()` exists in `diagnostics.py` but isn't wired into `model_builder.py`'s remediation loop (Cook's distance covers the same "which observation is a problem" purpose, used instead).
- Universe is fixed at 36 hand-picked symbols - extending toward the full non-financial listing (~1871 symbols) would reuse `regression/universe.py`'s throttled-load pattern at market scale.

## Open decisions still waiting on you

- Whether a future `fact_ranking` table belongs in `financial_reports.db` or a separate database file/table.
- Whether `fact_price` (currently just a parquet day-cache in `price_access.py`, per DATA_MODEL.md) should move into the same star schema for permanent history, or stay as-is until something needs it.
- Whether a standalone Piotroski F-score module is still wanted alongside the regression approach (see step 4 above) - the two aren't mutually exclusive, just not both built.
- The `net_margin` negative-coefficient result above - worth a second pass before trusting it.
