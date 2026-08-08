# VNQuant — System Overview

**Status: you are the approver.** Nothing below Step 1 has been built. I will not implement,
install, or commit anything further until you explicitly say which piece to build next. This
document exists so you can review the architecture and the underlying concepts before that
happens.

---

## 1. Program system (architecture)

### 1.1 Goal
Rank Vietnamese stocks (HOSE/HNX/UPCOM) by investment attractiveness, using two independent
engines whose outputs get combined into one score:

- A **Fundamental Engine** — is the business healthy and reasonably priced?
- A **Statistical Engine** — what does the stock's own price history suggest about likely
  near-term drift and risk?

Both engines are code you read, understand, and can modify — not calls into someone else's
opaque scoring function.

### 1.2 Layers

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend — React + TS         ranked list · stock detail page │
├──────────────────────────────────────────────────────────────┤
│  Backend — FastAPI             thin API + SQLite persistence   │
├──────────────────────────────────────────────────────────────┤
│  Composite Index Engine        combine + rank                  │
├───────────────────────────┬────────────────────────────────────┤
│  Fundamental Engine        │  Statistical / Time-Series Engine  │
│  value & quality ratios,   │  ARIMA (return/trend), GARCH        │
│  Piotroski-style score     │  (volatility), beta vs VN-Index     │
├───────────────────────────┴────────────────────────────────────┤
│  Data Ingestion Layer          vnstock wrappers + local cache    │
└──────────────────────────────────────────────────────────────┘
```

A layer only ever calls the layer(s) directly below it. The Composite Index Engine never
touches vnstock or raw financial statements directly — only the numbers the two engines
above it already produced and you already hand-verified. That boundary is what makes each
piece testable in isolation.

### 1.3 Folder structure (what exists on disk right now)

```
financial_tool/
  .venv/                  <- isolated Python 3.14 environment (not shared with rest of machine)
  pyproject.toml          <- package "vnquant", pinned deps (vnstock==4.0.2, numpy, pandas, scipy)
  src/vnquant/
    __init__.py            (version 0.1.0)
    _console.py            <- forces UTF-8 stdout so Vietnamese text doesn't crash the console
    data/                   <- EMPTY — Step 2 (not started)
    fundamentals/            <- EMPTY — Step 3 (not started)
    timeseries/              <- EMPTY — Step 4 (not started)
    scoring/                  <- EMPTY — Step 5 (not started)
  data_cache/               <- EMPTY, gitignored — will hold cached vnstock fetches
  README.md                <- setup + workflow instructions
  docs/SYSTEM_OVERVIEW.md   <- this file
```

`backend/` and `frontend/` don't exist yet — they get created in Steps 6-7, after the
library itself is built and verified. Git has been initialized locally but **nothing has
been committed yet** — that first commit is on hold pending your review of this document.

### 1.4 Tech stack and why

| Layer | Technology | Why |
|---|---|---|
| Data source | `vnstock` 4.0.2 | Already installed on this machine; confirmed working for VN price history, financial statements, ticker listings |
| Array/data plumbing | numpy, pandas | Standard, already installed — not "the method," just the data structures the method operates on |
| Statistical algorithms | Hand-written (this is the actual "own library" work) | AR/ARIMA and GARCH implemented from their mathematical definitions using numpy + scipy's optimizer, not `statsmodels`/`arch` calls |
| Persistence | SQLite via SQLAlchemy | Zero setup (file-based), already installed, sufficient for a single-user local app |
| Backend | FastAPI + uvicorn | Already installed; thin wrapper, no business logic lives here |
| Frontend | React + TypeScript + Vite | Node/npm already installed; no new tooling needed |
| Verification | None (by design) | No separate demo/test framework — every module runs standalone and is checked by hand each time; see Section 2.1 |

---

## 2. Flow

### 2.1 Build-time flow (how each piece gets made — applies to every function/algorithm)

No separate demo or test folders — every module is runnable **standalone**, like a script:

```
 write function inside its real module  -->  run that file directly  -->  YOU read the output
        (with an `if __name__ == "__main__":` block                          |
         that exercises it on real tickers)                                  v
                                                                            commit
```

1. Implement one function or algorithm inside its real file, e.g. `src/vnquant/data/cache.py`.
2. Add an `if __name__ == "__main__":` block in that same file that runs it against real data
   and prints the result.
3. You run that one file yourself: `.venv/Scripts/python.exe -m vnquant.data.cache`.
4. You check the output — against cafef.vn / a broker app for ratios, or against a synthetic
   series with a known, designed-in answer for ARIMA/GARCH (Section 3.2 explains why.)
5. Commit once you're satisfied. Every commit is one verified brick.

There's no automated regression net here by design — nothing is frozen or re-checked for
you. If a later change touches something an earlier module depends on, the way to catch a
break is the same as the way you verified it originally: run that file again and look. Nothing
moves to the next brick until you've signed off on the current one.

### 2.2 Runtime flow (once the system is built — not yet, for context)

```
vnstock (live) --> data_cache/ (parquet) --> Fundamental Engine   --\
                                          \-> Statistical Engine   --> Composite Index Engine
                                                                          |
                                                                          v
                                                              SQLite (persisted ranking run)
                                                                          |
                                                                          v
                                                        FastAPI  -->  React frontend
```

A manual script (`backend/scripts/run_ranking.py`, built in Step 6) triggers one full pass:
fetch/cache data for the universe, compute both engines' outputs, combine into the composite
score, persist the ranked list. The frontend only ever reads the already-computed, already
-persisted result — it never triggers computation itself in v1.

### 2.3 Where we are right now

**Done (Step 1 — scaffolding):** git initialized, isolated venv, `pyproject.toml`, folder
structure, package installs and imports correctly, Windows console UTF-8 issue fixed and
verified. **Not committed yet.**

**Not started:** everything else. Steps 2-8 (data ingestion, Fundamental Engine, Statistical
Engine, Composite Index Engine, backend, frontend, backtest sanity check) are all pending your
go-ahead, one brick at a time.

---

## 3. Applied knowledge (the concepts behind each engine)

This section is the "why," independent of code, so you can agree or disagree with the
approach before it's implemented.

### 3.1 Fundamental Engine concepts

| Concept | What it measures | Formula (as this project will compute it) | Read on it |
|---|---|---|---|
| P/E (Price/Earnings) | How expensive the stock is relative to the profit it generates | `price / (net_profit / shares_outstanding)` | Low P/E *can* mean cheap — or can mean the market expects earnings to fall (a "value trap"). Never used alone. |
| P/B (Price/Book) | How the market values the company vs. its accounting net worth | `price / (total_equity / shares_outstanding)` | More meaningful for asset-heavy businesses; less meaningful for asset-light/high-growth ones. |
| ROE (Return on Equity) | How efficiently the company turns shareholders' capital into profit | `net_profit / total_equity` | High ROE is good, but can be inflated by heavy debt (leverage) — that's why leverage is scored separately, not ignored. |
| ROA (Return on Assets) | Profit relative to everything the company owns, debt-funded or not | `net_profit / total_assets` | A cross-check on ROE — a company with high ROE but low ROA is leaning on debt. |
| Margins (gross/operating/net) | Operational efficiency at each stage of the income statement | revenue/profit-based ratios from the income statement | Trends matter more than single-period snapshots. |
| Growth (revenue, profit) | Trajectory, not just a snapshot | YoY %, and ~3-year growth (bounded by vnstock only returning 4 periods — see Section 4) | A cheap-and-shrinking company is not the same opportunity as a cheap-and-growing one. |
| Debt/Equity, Current Ratio | Financial safety margin | balance-sheet ratios | Excluded entirely for banks/securities/insurers in v1 — their balance sheets don't have a comparable "current assets" concept, so the ratio is structurally meaningless for them, not just noisy. |
| **Piotroski F-Score** | A 0-9 composite "is this a quality business" checklist, built entirely from the ratios above | Sum of 9 yes/no signals: profitability (ROA>0, cash flow from ops>0, ROA improving, cash flow > net income), leverage/liquidity (leverage decreasing, current ratio improving, no new share dilution), efficiency (gross margin improving, asset turnover improving) | Originally Joseph Piotroski's method (2000) for separating winners from losers within cheap (high book-to-market) stocks. Used here as a quality gate/signal alongside valuation, not a replacement for it. |

### 3.2 Statistical / Time-Series Engine concepts

| Concept | What it does | Why hand-built here |
|---|---|---|
| **AR(p) — Autoregression** | Models a value (e.g. today's return) as a weighted sum of its own past `p` values, plus noise: `r_t = c + φ₁r_{t-1} + ... + φₚr_{t-p} + ε_t` | Solvable in closed form (least squares / Yule-Walker equations) — the simplest real forecasting model, and a good first brick before adding complexity. |
| **ARIMA(p,d,q)** | AR, plus differencing `d` times to make a non-stationary series (e.g. raw prices, which trend) stationary (e.g. returns), plus an MA(`q`) term modeling the effect of past forecast *errors* | The standard classical toolkit for "what's the likely near-term drift of this series based only on its own history." Fitting the MA term requires numerical optimization (no closed form), which is why it's a separate, later brick after plain AR. |
| **GARCH(1,1)** | Models *volatility clustering* — the empirical fact that big price moves tend to be followed by more big moves (calm and turbulent periods cluster). Conditional variance: `σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}` | Gives a forward-looking risk estimate per stock instead of just a trailing standard deviation. Parameters (`ω, α, β`) are fit by maximizing the likelihood of the observed returns — a numerical optimization problem, done here with `scipy.optimize`, not `arch_model`. |
| **Beta vs. VN-Index** | Systematic risk — how much a stock tends to move for a given move in the whole market | `cov(stock returns, VN-Index returns) / var(VN-Index returns)` | The classical market-risk measure; cheap to compute once return series exist from the models above. |

**Why "hand-built" is feasible and how it gets checked**: these are 40-70-year-old, well
-documented classical statistics methods (Box-Jenkins ARIMA methodology dates to 1970; GARCH
to Bollerslev, 1986) — not research-frontier ML. Verification uses two techniques together:
1. Simulate a series from *known* parameters (e.g. an AR(1) process with φ=0.6 you generated
   yourself) and confirm the fitting procedure recovers a value close to 0.6. This is the
   primary, reproducible correctness check.
2. As a one-time sanity check on real stock data, compare your fitted parameters against
   `statsmodels`/`arch` (already installed) — used only as an offline answer key during
   development, never called at runtime by the shipped library.

### 3.3 Composite Index Engine concepts

| Concept | What it does | Why it's needed |
|---|---|---|
| **Cross-sectional z-score** | Converts a raw ratio (e.g. P/E = 15) into "how many standard deviations from the universe average" (`(x - mean) / std`, computed across all stocks in the universe at once) | Raw ratios aren't comparable across companies with different scales/units. Z-scores put P/E, ROE, growth %, and volatility all on the same -3..+3-ish scale so they can be added together meaningfully. |
| **Sign convention** | Some ratios are "lower is better" (P/E, P/B, debt/equity, volatility) and some are "higher is better" (ROE, growth). "Lower is better" ones get negated before combining. | Without this, a composite score would nonsensically reward being *expensive* and *risky*. This is the single easiest silent bug in the whole system — flagged explicitly so it gets a dedicated hand-test. |
| **Weighted composite** | `score = w1·z(value) + w2·z(quality) + w3·z(growth) + w4·z(expected_return) - w5·z(volatility) + ...` with weights you choose and can name/tune | This *is* the investment philosophy, made explicit and adjustable, instead of buried in a black box. Default proposal: equal-weight the major buckets to start, then you retune based on what the ranked output looks like. |

### 3.4 Validation concepts

| Concept | What it means | The catch, for this specific data source |
|---|---|---|
| **Point-in-time correctness** | When testing "would this method have picked winners historically," you must only use data that was *actually public* at that past date — not later-restated figures. | Vietnamese annual reports are typically filed ~90 days after fiscal year-end, so FY2022 numbers weren't public on Jan 1 2023. |
| **Look-ahead bias** | Accidentally letting "future" information leak into a "past" decision, which makes a backtest look artificially good | `vnstock` only exposes the latest/restated version of financial statements, with no original-filing-date field — so this project can only *approximate* point-in-time correctness (fixed publish-lag assumption), not guarantee it. Labeled as a plausibility check, not proof, everywhere it appears. |

---

## 4. Known constraints worth your attention

These are facts confirmed by testing the actual `vnstock` API on this machine, not
assumptions — they shape what's realistic to build:

- Financial statements return only **~4 periods** by default (4 years or 4 quarters) — bounds
  growth-rate calculations to roughly a 3-year figure, not 5-year.
- `vnstock`'s own built-in `Finance.ratio()` returned empty/malformed data when tested — not
  used anywhere in this design.
- Price data from one endpoint is in thousands of VND, another endpoint is in raw VND —
  normalized to raw VND once at the data-ingestion boundary so it's consistent everywhere
  above that layer.
- Banks/securities firms/insurers report fundamentally different balance-sheet structures (no
  "current assets"/"inventory" concept) — excluded from the v1 comparable universe rather than
  forced into ratios that don't apply to them.

## 5. Decisions currently defaulted — flag any you'd like changed

- Starting universe: VN30 constituents minus financial-sector names (~15-20 liquid stocks).
- Composite weights: equal-weighted buckets as a starting point, meant to be retuned by you.
- Time-series scope: AR → full ARIMA → GARCH(1,1) → beta, in that order. No LSTM, no ML
  ensembles, no Monte Carlo — kept out deliberately (see `reference/finance101/` for what
  happens when scope isn't kept in check).
- Package name: `vnquant`.

## 6. What happens next

Nothing, until you tell me to proceed. When you're ready, tell me which brick to start —
most likely Step 2 (`data/cache.py`, the local parquet cache with no external dependency) —
or tell me what to change in this document first.
