# Data model: dimensions + facts

Proposal for evolving the current flat `statement_lines` table into a small star schema,
before `init_market_financials()` runs at full-universe scale — this is the cheap moment to
change shape; after ~1871 symbols x 8 quarters x 3 statements are loaded it's a real migration.

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
        is_bank, listing_date                          |
        is_in_universe (bool, precomputed)              |
              ^                                          |
              |                                          |
              +-------------- fact_statement_line -------+
              |                symbol   (FK)
              |                period   (FK) --------> dim_period
              |                item_id  (FK)            period (PK, e.g. "2025Q4")
              |                value                    fiscal_year, fiscal_quarter
              |                fetched_on                period_end_date
              |                                          estimated_publish_date (+~90d lag)
              |
              +-------------- fact_price
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

        dim_sector
        icb_code (PK)
        icb_name, icb_level
        parent_icb_code -> dim_sector   (self-FK, for the ICB hierarchy)
        is_financial_sector (bool, precomputed — the bank/broker/insurer exclusion rule)
```

## Grain — the one rule that matters most per table

- `fact_statement_line`: one row per (symbol, period, item_id). Not per statement_type — that's
  implied by `item_id -> dim_statement_item.statement_type`, *if* item_id numbering never
  overlaps across statement types in vnstock's own taxonomy. Worth a quick check against the
  real VNM data already loaded before dropping `statement_type` from the fact key; if it turns
  out item_id does overlap, keep `statement_type` in the primary key too.
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

- SQLite doesn't enforce foreign keys unless `PRAGMA foreign_keys = ON` is set per connection
  — easy to forget with SQLAlchemy, worth adding explicitly (an `event.listens_for` hook on
  `Engine.connect`, or `connect_args={"check_same_thread": False}` isn't it — needs the
  literal `PRAGMA` call).
- `dim_symbol` and `dim_sector` are treated as type-1 (overwrite, no history) for now — fine
  since nothing downstream needs "what sector was this classified as a year ago" yet. Flag if
  that changes.
- This is a proposal, not yet applied to the real `financial_reports.db` — the existing
  1504-row VNM data would need reloading under the new shape, which is exactly why doing this
  before the full-universe backfill is cheaper than after.