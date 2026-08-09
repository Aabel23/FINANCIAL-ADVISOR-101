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

- `src/market_access/` — data layer. `db.py` (shared SQLAlchemy star schema), `financial_report.py`
  (statement ingestion), `price_access.py` (price fetch).
- `src/valuation/` — `dcf.py`, `ddm.py`, `graham.py`, `nav.py`, `relative.py`, `rim.py`.
- `src/regression/` — `ols.py`, `model_builder.py`, `diagnostics.py`, `universe.py`, `_features.py`.
- `src/metrics/` — `error_metrics.py`.
- `database/` — `financial_reports.sql` (tracked in git, the source of truth: full schema+data
  dump) and `financial_reports.db` (gitignored SQLite file the app actually reads/writes,
  rebuilt from the `.sql` automatically on first use if missing — see `db._restore_from_sql_dump`).
- `data_cache/` — gitignored parquet cache of vnstock fetches.

Each folder under `src/` installs as its own top-level package (`pip install -e .` from
`pyproject.toml`), so import as `from valuation import dcf`, not `from vnquant.valuation import dcf`.

## Workflow

No separate demo/test folders, no automated test suite. Every module runs standalone: it has
an `if __name__ == "__main__":` block that exercises it against real tickers and prints the
result, so you run that one file and read the output yourself, e.g.:

```bash
.venv/Scripts/python.exe -m valuation.dcf
.venv/Scripts/python.exe -m market_access.db
```

1. Write/change a function.
2. Run its file directly.
3. Check the printed output by hand (cafef.vn, a broker app, or a hand calculation).
4. If the change touched the database, run `market_access.db.dump_to_sql()` to refresh
   `database/financial_reports.sql` before committing — that file is the tracked source of
   truth, not the gitignored `.db`.
5. Commit once it looks right.

Nothing is frozen or re-checked automatically — if you change a module that others depend on
(e.g. `market_access/db.py`), re-run those dependents' files too to confirm they still look right.