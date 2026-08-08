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
3. ~~Round out data crawling.~~ Done, then further split: price data stays in `price_access.py` (day-cache), financial statements moved to `financial_report.py` + `db.py` (permanent SQLite, star schema, whole-market scope) — see docs/DATA_MODEL.md. `Finance.ratio()` is still confirmed broken (empty output) in vnstock 4.0.2 regardless of period cap — ratios will be computed from the raw statements ourselves in step 4 next, not sourced from vnstock.
4. **Run `init_market_financials()` for the full universe**, then **start the math/quant folder** (`src/quant/`): P/E, P/B, ROE, ROA, margins, growth, leverage ratios computed by joining `fact_statement_line` + `dim_statement_item` + `price_access.py` data, then a filter function (per the earlier P/E-P/B filter discussion), then the Piotroski-style score. Simple arithmetic first — good place to resume the hand-verify-against-cafef.vn habit.
5. ~~`database/` folder's exact scope.~~ Settled: SQLite via SQLAlchemy, star schema (see DATA_MODEL.md), currently holds financial statement facts + symbol/sector/item/period dimensions. Whether a computed ranking run also lands here (as `fact_ranking`) or in a separate DB is still open — revisit once step 4 exists.
6. **Statistical engine** (AR/ARIMA, GARCH, beta vs VN-Index) — after the math/quant ratios are solid, since it's a harder verification problem (synthetic-data parameter recovery, not hand arithmetic).
7. **`main/` folder** — the local web host (FastAPI) + the entry point that loops over the universe. Threading/parallelism explicitly deferred until it's actually needed (see prior discussion — GIL makes plain threading ineffective for the CPU-bound math anyway).
8. **`frontend/`** — React ranked table + stock detail page, last.

## Open decisions still waiting on you

- Whether a future `fact_ranking` table belongs in `financial_reports.db` or a separate database file/table (see step 5).
- Whether `fact_price` (currently just a parquet day-cache in `price_access.py`, per DATA_MODEL.md) should move into the same star schema for permanent history, or stay as-is until something needs it.
