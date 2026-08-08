"""
Persists quarterly financial statements (balance sheet, income statement, cash
flow) for the whole market to a local SQLite database via SQLAlchemy.

Unlike price_access.py's per-day cache, this is permanent, accumulating
storage: vnstock only ever exposes a rolling window of the most recent periods
(confirmed live: 8 quarters with a registered free-tier API key, not full
history since listing), so real depth is built up over repeated calls to
update_market_financials() each quarter - not obtained in one shot.
"""

import sys
import time
from datetime import date

import pandas as pd
import vnstock
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from market_access.db import (
    DB_PATH,
    Sector,
    StatementItem,
    StatementLine,
    Symbol,
    ensure_period,
    ensure_statement_items,
    engine as _engine,
    sync_symbol_dimension,
)
from market_access.price_access import DATA_SOURCE, get_stock_universe

# Vietnamese item names crash print() under the default Windows console
# codepage unless stdout is forced to UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

_STATEMENTS = ("balance_sheet", "income_statement", "cash_flow")

# Free-tier API key is capped at 60 req/min (verified live against the vnai
# rate limiter). Stay under that with margin rather than lean on vnstock's own
# rate-limit recovery, which hard-exits the process via sys.exit() instead of
# raising something catchable.
_TARGET_REQUESTS_PER_MINUTE = 50
_CALLS_PER_SYMBOL = len(_STATEMENTS)
_SECONDS_PER_SYMBOL = 60 / (_TARGET_REQUESTS_PER_MINUTE / _CALLS_PER_SYMBOL)


def _melt_statement(df: pd.DataFrame, symbol: str, statement: str, fetched_on: str) -> tuple[list[dict], list[dict]]:
    """Splits vnstock's wide one-column-per-period shape into (item_rows,
    fact_rows): item_rows carry the item_id/item_vi/item_en/statement_type
    metadata (destined for dim_statement_item, deduped there), fact_rows
    carry only the keys + value (destined for fact_statement_line). Long
    format instead of vnstock's wide shape because banks/insurers/brokers/
    ordinary companies each have different line-item sets - a long table is
    the only shape that holds the whole heterogeneous market without a
    different schema per sector."""
    period_cols = [c for c in df.columns if c not in ("item", "item_en", "item_id")]
    melted = df.melt(
        id_vars=["item", "item_en", "item_id"], value_vars=period_cols, var_name="period", value_name="value"
    )
    item_rows = [
        {"item_id": row.item_id, "item_vi": row.item, "item_en": row.item_en, "statement_type": statement}
        for row in melted.itertuples(index=False)
    ]
    fact_rows = [
        {
            "symbol": symbol,
            "period": row.period,
            "item_id": row.item_id,
            "value": None if pd.isna(row.value) else float(row.value),
            "fetched_on": fetched_on,
        }
        for row in melted.itertuples(index=False)
    ]
    return item_rows, fact_rows


def _upsert_facts(rows: list[dict], session: Session) -> None:
    if not rows:
        return
    stmt = sqlite_insert(StatementLine).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "period", "item_id"],
        set_={"value": stmt.excluded.value, "fetched_on": stmt.excluded.fetched_on},
    )
    session.execute(stmt)


def _fetch_and_store(symbol: str, session: Session) -> None:
    """Pulls all 3 statement types for one symbol (quarterly) and upserts
    every line item into the DB in bulk. This is the one place that actually
    spends API calls - both init and update funnel through here. Assumes
    dim_symbol already has this symbol (sync_symbol_dimension must have run
    first - both init_market_financials and init_financial_history do this)."""
    finance = vnstock.Finance(source=DATA_SOURCE, symbol=symbol, period="quarter")
    fetched_on = date.today().isoformat()
    for statement in _STATEMENTS:
        df = getattr(finance, statement)()
        item_rows, fact_rows = _melt_statement(df, symbol, statement, fetched_on)
        ensure_statement_items(item_rows, session)
        for period in {row["period"] for row in fact_rows}:
            ensure_period(period, session)
        _upsert_facts(fact_rows, session)
    session.commit()


def init_financial_history(symbol: str) -> None:
    """Full backfill for one symbol: stores whatever periods vnstock
    currently exposes. NOT the company's full history since listing - vnstock
    caps the window it returns regardless of get_all (confirmed live: 8
    quarters with a free-tier key). update_latest_quarter grows real depth
    over time, one quarter at a time, from here on."""
    with Session(_engine) as session:
        # fact_statement_line has a real FK to dim_symbol now (foreign_keys=ON
        # in db.py) - the symbol has to exist there first or the insert fails.
        sync_symbol_dimension(session)
        _fetch_and_store(symbol, session)


def _previous_quarter_label(today: date) -> str:
    """The most recent calendar quarter that should already be reportable as
    of `today` - not the quarter we're currently in. E.g. any day in
    2026-Q3 returns "2026-Q2"."""
    current_q = (today.month - 1) // 3 + 1
    if current_q == 1:
        return f"{today.year - 1}-Q4"
    return f"{today.year}-Q{current_q - 1}"


def _has_period(symbol: str, period: str, session: Session) -> bool:
    # Any row is enough to stand in for "this symbol is up to date": statement
    # type isn't part of the fact table's key anymore (it's reachable via
    # item_id -> dim_statement_item), and _fetch_and_store always writes all
    # 3 statement types for a symbol in the same transaction, so they can't
    # independently fall out of sync.
    stmt = select(StatementLine.symbol).where(StatementLine.symbol == symbol, StatementLine.period == period).limit(1)
    return session.execute(stmt).first() is not None


def update_latest_quarter(symbol: str) -> bool:
    """Updates one symbol only if its most recently expected quarter isn't
    stored yet. Returns True if it actually hit the API, False if skipped.
    The skip check is a local DB query only, so repeated runs within the same
    quarter cost nothing once every symbol has been caught up."""
    expected = _previous_quarter_label(date.today())
    with Session(_engine) as session:
        if _has_period(symbol, expected, session):
            return False
        # Only synced on the fetch path, not the skip path above - keeps a
        # fully-caught-up re-run genuinely zero-cost, not just zero-API-calls.
        sync_symbol_dimension(session)
        _fetch_and_store(symbol, session)
        return True


def init_market_financials(symbols: list[str] | None = None) -> None:
    """Backfills the whole market (or a given symbol list). Every symbol
    costs an API call - there's nothing to skip on a first run - so this is
    throttled to stay under the free-tier rate limit. For the full
    ~1871-symbol universe, expect roughly 90-100 minutes."""
    symbols = symbols or get_stock_universe()
    for i, symbol in enumerate(symbols, 1):
        start = time.monotonic()
        try:
            init_financial_history(symbol)
            print(f"[{i}/{len(symbols)}] {symbol}: OK")
        except Exception as e:
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED - {e}")
        elapsed = time.monotonic() - start
        if elapsed < _SECONDS_PER_SYMBOL:
            time.sleep(_SECONDS_PER_SYMBOL - elapsed)


def update_market_financials(symbols: list[str] | None = None) -> None:
    """Quarterly refresh for the whole market (or a given symbol list).
    Symbols already caught up for the expected quarter are skipped with no
    API call and no throttling delay, so a re-run after the first full pass
    of a quarter is fast."""
    symbols = symbols or get_stock_universe()
    fetched = skipped = failed = 0
    for i, symbol in enumerate(symbols, 1):
        try:
            start = time.monotonic()
            if update_latest_quarter(symbol):
                fetched += 1
                elapsed = time.monotonic() - start
                if elapsed < _SECONDS_PER_SYMBOL:
                    time.sleep(_SECONDS_PER_SYMBOL - elapsed)
                print(f"[{i}/{len(symbols)}] {symbol}: fetched")
            else:
                skipped += 1
                print(f"[{i}/{len(symbols)}] {symbol}: skipped (already up to date)")
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED - {e}")
    print(f"\ndone: {fetched} fetched, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    print(f"=== DB: {DB_PATH} ===")

    print("\n=== 1. Init financial history for VNM ===")
    init_financial_history("VNM")
    with Session(_engine) as session:
        rows = session.execute(select(StatementLine).where(StatementLine.symbol == "VNM")).all()
        periods = sorted({r[0].period for r in rows})
        print(f"{len(rows)} line items stored for VNM, periods covered: {periods}")

        print("\n=== 2. Dimensional join: item breakdown by statement_type (via dim_statement_item) ===")
        breakdown = session.execute(
            select(StatementItem.statement_type, func.count())
            .select_from(StatementLine)
            .join(StatementItem, StatementLine.item_id == StatementItem.item_id)
            .where(StatementLine.symbol == "VNM")
            .group_by(StatementItem.statement_type)
        ).all()
        print(dict(breakdown))
        assert set(dict(breakdown)) == set(_STATEMENTS), "expected all 3 statement types present"

        print("\n=== 3. dim_symbol / dim_sector join for VNM vs VCB ===")
        for sym in ("VNM", "VCB"):
            row = session.get(Symbol, sym)
            sector = session.get(Sector, row.icb_code) if row.icb_code else None
            print(
                f"{sym}: {row.organ_name!r}, sector={sector.icb_name if sector else None!r}, "
                f"is_financial_sector={row.is_financial_sector}"
            )

    print("\n=== 4. Update latest quarter for VNM (should skip - just fetched) ===")
    did_fetch = update_latest_quarter("VNM")
    print(f"hit the API: {did_fetch} (expected False)")
    assert did_fetch is False, "expected a skip since VNM was just fully refreshed"

    print("\n=== 5. Expected-quarter label sanity check ===")
    today = date.today()
    print(f"today={today.isoformat()} -> previous completed quarter={_previous_quarter_label(today)}")