# vnquant

Hand-built quantitative library + web app for ranking Vietnam stock market (HOSE/HNX/UPCOM)
equities: fundamental ratios + ARIMA/GARCH time-series signals + a composite ranking index.

## Setup

```bash
# from financial_tool/
.venv/Scripts/python.exe -m pip install -e .
```

Windows console note: Vietnamese text (company/sector names) can crash `print()` under the
default console codepage. Either set `PYTHONUTF8=1` in your shell before running scripts, or
just `import vnquant._console` first thing in any script that prints vnstock data.

OpenBLAS note: bare `numpy` import can fail with `OpenBLAS error: Memory allocation still
failed after 10 retries, giving up.` in this shell. Fix: set `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1` before running, e.g. (Git Bash):
```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/Scripts/python.exe src/data_crawling/market_access.py
```

## Layout

- `src/vnquant/` — the library. `data/` (vnstock wrappers + cache), `fundamentals/` (ratios,
  Piotroski score), `timeseries/` (AR/ARIMA, GARCH, beta — hand-implemented), `scoring/`
  (cross-sectional z-scores, composite index, ranking).
- `data_cache/` — gitignored parquet cache of vnstock fetches.
- `backend/`, `frontend/` — FastAPI + React, added once the library is solid.

## Workflow

No separate demo/test folders. Every module is runnable standalone: each file gets its own
`if __name__ == "__main__":` block that exercises it against real tickers and prints the
result, so you can run that one file directly and read the output yourself, e.g.:

```bash
.venv/Scripts/python.exe -m vnquant.data.cache
```

Write the function -> run its file directly -> you check the output by hand (against
cafef.vn, a broker app, or a hand calculation) -> commit once you're satisfied. Nothing is
frozen or re-checked automatically — if you change something that an earlier module depends
on, re-run that module's file again to confirm it still looks right.
