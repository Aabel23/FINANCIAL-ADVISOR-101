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
      financial_report.py            <- DONE: quarterly balance sheet / income statement / cash flow
                                         for the whole market, persisted permanently to SQLite (not a
                                         day-cache — see "Financial data model" below)
  docs/
    SYSTEM_OVERVIEW.md              <- architecture + concepts reference (written before some of
                                       the structure changes below — folder names there are stale)
    NEXT_STEPS.md                   <- this file
  README.md
```

Git: initialized, 2 commits made (scaffolding + market_access.py; cache/normalization/statements round-out). **The rename to `market_access/` + split into `price_access.py`/`financial_report.py` + the SQLite persistence layer below are all uncommitted** — next commit should cover this.

vnstock account: a free-tier API key is registered locally (`~/.vnstock/api_key.json`, outside the repo). This raised limits from guest (20 req/min, 4 statement periods/call) to free (**60 req/min, 3600/hour, 10000/day, 8 statement periods/call** — confirmed live, higher than originally assumed).

## Financial data model (new — read before touching `financial_report.py`)

- **Storage**: SQLite via SQLAlchemy 2.0 ORM (`database/financial_reports.db`), not parquet — chosen specifically because this needs permanent accumulation across quarters plus cross-symbol queries later (ranking), unlike the day-cache in `price_access.py`.
- **Shape**: one table `statement_lines`, tidy/long format (`symbol, statement, period, item_id, item_vi, item_en, value, fetched_on`), composite primary key on the first four. Long format because banks/insurers/brokers/ordinary companies have different line-item sets — no single wide schema fits the whole market.
- **Universe**: `get_stock_universe()` from `price_access.py` — excludes investment funds (`com_type_code == "QU"`), keeps companies/banks/insurers/brokers (~1871 symbols).
- **History depth ceiling**: vnstock never returns more than a rolling window regardless of `get_all` — confirmed live at 8 quarters (~2 years) with the registered key. **True full history since IPO is not obtainable in one call from this source.** Depth beyond the initial 8 quarters can only be built by running `update_market_financials()` every quarter from now on, indefinitely — there's no shortcut.
- **Two entry points**: `init_market_financials()` (first-ever backfill, always calls the API per symbol, ~90-100 min throttled for the full universe) vs. `update_market_financials()` (quarterly refresh — skips any symbol whose expected previous-quarter data is already stored, at zero API cost and zero delay for skips).
- **Not yet run at market scale** — only tested against a single symbol (VNM: 1504 rows across all 3 statements, 8 quarters). Running `init_market_financials()` for the full ~1871-symbol universe is still to do.

## Immediate next steps, in order

1. ~~Resolve the `src/vnquant/` leftover.~~ Deleted — superseded by `src/data_crawling/` (later renamed `src/market_access/`).
2. ~~First commit.~~ Done.
3. ~~Round out data crawling.~~ Done, then further split: price data stays in `price_access.py` (day-cache), financial statements moved to `financial_report.py` (permanent SQLite, whole-market scope) — see "Financial data model" above. `Finance.ratio()` is still confirmed broken (empty output) in vnstock 4.0.2 regardless of period cap — ratios will be computed from the raw statements ourselves in step 4 next, not sourced from vnstock.
4. **Run `init_market_financials()` for the full universe**, then **start the math/quant folder** (`src/quant/`): P/E, P/B, ROE, ROA, margins, growth, leverage ratios computed from `statement_lines` + `price_access.py` data, then a filter function (per the earlier P/E-P/B filter discussion), then the Piotroski-style score. Simple arithmetic first — good place to resume the hand-verify-against-cafef.vn habit.
5. ~~`database/` folder's exact scope.~~ Settled: SQLite via SQLAlchemy, currently holds `statement_lines` (financial statements). Whether a computed ranking run also lands here, in a separate table or DB, is still open — revisit once step 4 exists.
6. **Statistical engine** (AR/ARIMA, GARCH, beta vs VN-Index) — after the math/quant ratios are solid, since it's a harder verification problem (synthetic-data parameter recovery, not hand arithmetic).
7. **`main/` folder** — the local web host (FastAPI) + the entry point that loops over the universe. Threading/parallelism explicitly deferred until it's actually needed (see prior discussion — GIL makes plain threading ineffective for the CPU-bound math anyway).
8. **`frontend/`** — React ranked table + stock detail page, last.

## Open decisions still waiting on you

- Whether a future ranking-run table belongs in `financial_reports.db` or a separate database file/table (see step 5).
- Commit checkpoint: the rename + split + SQLite layer described above is all still uncommitted.
