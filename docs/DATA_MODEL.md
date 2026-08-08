# Data model: dimensions + facts

**Status: implemented and verified** in `src/market_access/db.py` (schema) and
`src/market_access/financial_report.py` (loader), against real VNM/VCB data — see the
verification note near the bottom. Corrections from the original proposal, made after
checking real data rather than assumption (details inline below): `dim_sector` has no
`parent_icb_code` self-FK (vnstock's 4 ICB levels aren't linked that way in the data);
`is_financial_sector` is a plain function of `com_type_code`, not a stored column; and
investment funds (`com_type_code == "QU"`) are excluded from `dim_symbol` entirely rather than
flagged — they don't file the statements this schema exists to hold, so there's no reason to
carry them at all. `is_fund` and `is_financial_sector` were briefly stored boolean columns on
`dim_symbol`, dropped once it was clear `com_type_code` already says everything they encoded.

The rest of this document is the original design reasoning, left as-is since it's still why
the shape looks the way it does.

## Why dimensionalize at all

`statement_lines` today repeats `item_vi`/`item_en` on every single row — the same ~200-ish
line-item labels copied out thousands of times. Pulling those into a dimension table means
one canonical place to look up what an `item_id` means, and the fact rows shrink to just keys
+ a number. Same logic applies to symbol metadata (company name, sector) once `fact_price`
exists alongside `fact_statement_line` — company info shouldn't live twice.

## Shape

```
        dim_symbol                         dim_statement_item
        symbol (PK)                        item_id (PK)
        organ_name                         item_vi, item_en
        com_type_code                      statement_type (balance_sheet/income/cashflow)
        icb_code -> dim_sector                        ^
        (funds excluded entirely -                      |
         see is_financial_sector() below)                |
              ^                                            |
              |                                             |
              +-------------- fact_statement_line -------+
              |                symbol   (FK)
              |                period   (FK) --------> dim_period
              |                item_id  (FK)            period (PK, e.g. "2026-Q2")
              |                value                    fiscal_year, fiscal_quarter
              |                fetched_on                period_end_date
              |                                          estimated_publish_date (+90d lag)
              |
              +-------------- fact_price               (future — not built yet)
              |                symbol (FK)
              |                date
              |                open, high, low, close, volume   (raw VND, normalized)
              |                fetched_on
              |
              +-------------- fact_ranking            (future — not built yet)
                               symbol  (FK)
                               run_id  (FK) --------> dim_ranking_run
                               composite_score, rank                run_id (PK)
                                                                     run_date, weights_json

        dim_sector                          (flat lookup, no hierarchy - see note below)
        icb_code (PK)
        icb_name, icb_level
```

**Corrections from the original proposal**: vnstock's 4 ICB levels per symbol have no
`parent_icb_code` in the data (confirmed live - e.g. AAA's codes are 1000/1300/1350/1353, not
a prefix chain), so `dim_sector` is a flat lookup, not a self-referencing hierarchy.
`dim_symbol.icb_code` points at the most specific (level-4) code available.
`is_financial_sector(com_type_code)` is a plain function in `db.py`, not a stored column -
`com_type_code` (`NH`=bank, `CK`=broker, `BH`=insurer, already present in the source listing,
already reliable) is the source of truth, so deriving on demand beats storing a value that can
drift out of sync. Same reasoning removed `is_fund`: funds (`com_type_code == "QU"`) are
filtered out of `dim_symbol` before insert (`sync_symbol_dimension`), so no flag is needed -
every row that exists is a real operating company/bank/broker/insurer, by construction.

## Grain — the one rule that matters most per table

- `fact_statement_line`: one row per (symbol, period, item_id). Not per statement_type — that's
  implied by `item_id -> dim_statement_item.statement_type`. **Checked against real VNM data
  before implementing**: 188 distinct item_ids, zero shared across statement types — safe to
  drop `statement_type` from the fact key. `ensure_statement_items()` in `db.py` still raises
  if a future symbol ever violates this, rather than silently corrupting the dimension.
- `fact_price`: one row per (symbol, date). No separate `dim_date` — a plain date column is
  enough for a project this size; a calendar dimension (trading-day flags, Tet closures) is a
  reasonable later addition if gap-detection in the price history ever needs it, not before.
- `fact_ranking`: one row per (symbol, run_id). Whether per-factor contributions (P/E z-score,
  ROE z-score, ...) live as columns on this same row or as a separate finer-grained
  `fact_score_component` (symbol, run_id, factor_name, raw_value, zscore, contribution) is the
  one open modeling choice — wide row is simpler and matches "don't over-engineer"; the
  separate table is more flexible if you want to chart/query factor contributions later.

## Dimension population

No separate ETL step: when `financial_report.py` loads a line item with an `item_id` not yet
in `dim_statement_item`, upsert it there in the same pass. Same pattern for `dim_symbol`
(populate from `get_stock_universe()`'s listing pull) and `dim_sector` (from the ICB columns
already returned alongside it).

## Implementation notes

- SQLite doesn't enforce foreign keys unless `PRAGMA foreign_keys = ON` is set per connection —
  implemented via an `event.listens_for(engine, "connect")` hook in `db.py`.
- `dim_symbol` and `dim_sector` are type-1 (overwrite, no history) for now — fine since nothing
  downstream needs "what sector was this classified as a year ago" yet. Flag if that changes.
- `sync_symbol_dimension()` only does its real work (listing fetch + ~2000-row upsert) once per
  process, not once per symbol — added after noticing `init_market_financials()`'s per-symbol
  loop would otherwise repeat that upsert ~1871 times for no reason. `force=True` bypasses it.

## Verification

Re-ran against real data after implementing (`src/market_access/financial_report.py`'s
`__main__` block): VNM reload produced the same 1504 rows as the old flat table (976 balance
sheet + 328 cash flow + 200 income statement, confirmed via a join through
`dim_statement_item`), and the `dim_symbol`/`dim_sector` join correctly separates VNM
(`is_financial_sector=False`, sector "Thực phẩm") from VCB (`is_financial_sector=True`, sector
"Ngân hàng"). The old flat `statement_lines` table has been dropped from
`database/financial_reports.db`.

Re-verified again after dropping `is_fund`/`is_financial_sector` and excluding funds: migrated
the live DB in place (`DELETE ... WHERE com_type_code='QU'` removed 171 rows, then `ALTER TABLE
... DROP COLUMN` x2 - SQLite 3.35+ supports this natively, no table-recreate needed).
`sync_symbol_dimension()` now populates 1871 symbols (was 2042 with funds included, matching
`get_stock_universe()`'s known count exactly), and `db.py`'s `__main__` asserts a known fund
ticker (`FUEVFVND`, checked against the live listing first) is absent from `dim_symbol`.