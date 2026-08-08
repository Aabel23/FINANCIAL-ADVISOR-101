"""
Shared SQLAlchemy schema: a small star schema with dimension tables
(dim_symbol, dim_sector, dim_statement_item, dim_period) and fact tables
(fact_statement_line so far; fact_price and fact_ranking are planned but not
built yet - see docs/DATA_MODEL.md for the full proposal and reasoning).

financial_report.py (and later price_access.py, for fact_price) both read
and write through this one shared schema so dimensions aren't duplicated per
fact table.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import ForeignKey, create_engine, event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "financial_reports.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}")


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, _):
    # SQLite ignores FK constraints unless this is set per-connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


# Company types seen in the listing: CT=company, QU=investment fund,
# CK=securities firm, NH=bank, BH=insurer. Banks/brokers/insurers report
# fundamentally different statement structures than an operating company (no
# "current assets"/"inventory" concept) - not comparable with standard
# ratios. Flagged here once (from com_type_code, confirmed reliable and
# already available - not derived from ICB sector names) rather than
# re-derived by every later consumer.
_FINANCIAL_SECTOR_TYPE_CODES = {"NH", "CK", "BH"}


# ---- Dimensions ----------------------------------------------------------


class Sector(Base):
    """One row per ICB industry-classification code. vnstock exposes 4
    levels per symbol (1=broadest .. 4=most specific) with no explicit
    parent-child link between them in the data - confirmed live (e.g. AAA's
    codes are 1000/1300/1350/1353, not a prefix chain) - so this is a flat
    lookup, not a hierarchy tree."""

    __tablename__ = "dim_sector"

    icb_code: Mapped[str] = mapped_column(primary_key=True)
    icb_name: Mapped[str]
    icb_level: Mapped[int]


class Symbol(Base):
    """One row per ticker. Investment funds are excluded entirely (see
    sync_symbol_dimension) rather than flagged, so every remaining row is a
    real operating company/bank/broker/insurer. Sector classification stored
    at ICB level 4 (most specific available) as the single canonical
    classification for now.

    is_fund and is_financial_sector used to be stored columns here, derived
    from com_type_code - dropped as redundant: com_type_code already says
    what kind of business this is (CT=company, NH=bank, CK=broker,
    BH=insurer; QU=fund, excluded before rows ever get here). Use
    is_financial_sector(symbol.com_type_code) below instead of a stored flag."""

    __tablename__ = "dim_symbol"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    organ_name: Mapped[str | None]
    com_type_code: Mapped[str]
    icb_code: Mapped[str | None] = mapped_column(ForeignKey("dim_sector.icb_code"))


def is_financial_sector(com_type_code: str) -> bool:
    """Banks/brokers/insurers report fundamentally different statement
    structures than an operating company (no "current assets"/"inventory"
    concept) - not comparable with standard ratios."""
    return com_type_code in _FINANCIAL_SECTOR_TYPE_CODES


class StatementItem(Base):
    """One row per unique financial-statement line-item code. item_id is
    globally unique across statement types - checked against the real VNM
    data already loaded (188 distinct item_ids, zero shared across
    statement types) before relying on this; see docs/DATA_MODEL.md. If a
    future symbol (e.g. a bank) ever violates this, upsert_statement_item
    below will raise rather than silently corrupt the dimension."""

    __tablename__ = "dim_statement_item"

    item_id: Mapped[str] = mapped_column(primary_key=True)
    item_vi: Mapped[str | None]
    item_en: Mapped[str | None]
    statement_type: Mapped[str]  # balance_sheet | income_statement | cash_flow


class Period(Base):
    """One row per fiscal quarter. estimated_publish_date is a fixed
    +90-day assumption (VN annual reports file roughly 90 days after
    fiscal year-end) - an approximation, not each company's real filing
    date. Not used yet; carried for the point-in-time backtest planned
    later."""

    __tablename__ = "dim_period"

    period: Mapped[str] = mapped_column(primary_key=True)  # e.g. "2026-Q2"
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    period_end_date: Mapped[date]
    estimated_publish_date: Mapped[date]


# ---- Facts ----------------------------------------------------------------


class StatementLine(Base):
    """One line item, for one symbol, for one quarter. Grain: (symbol,
    period, item_id). statement_type is intentionally not part of this
    table - it's reachable via item_id -> dim_statement_item.statement_type
    instead of being repeated on every fact row."""

    __tablename__ = "fact_statement_line"

    symbol: Mapped[str] = mapped_column(ForeignKey("dim_symbol.symbol"), primary_key=True)
    period: Mapped[str] = mapped_column(ForeignKey("dim_period.period"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("dim_statement_item.item_id"), primary_key=True)
    value: Mapped[float | None]
    fetched_on: Mapped[str]  # ISO date, for auditing/debugging only


Base.metadata.create_all(engine)


_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_PUBLISH_LAG_DAYS = 90


def period_label_to_row(period: str) -> dict:
    """'2026-Q2' -> its dim_period row. Pure/deterministic, no I/O."""
    year_s, q_s = period.split("-Q")
    year, quarter = int(year_s), int(q_s)
    month, day = _QUARTER_END[quarter]
    period_end = date(year, month, day)
    return {
        "period": period,
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "period_end_date": period_end,
        "estimated_publish_date": period_end + timedelta(days=_PUBLISH_LAG_DAYS),
    }


def ensure_period(period: str, session: Session) -> None:
    row = period_label_to_row(period)
    stmt = sqlite_insert(Period).values(**row).on_conflict_do_nothing(index_elements=["period"])
    session.execute(stmt)


def ensure_statement_items(rows: list[dict], session: Session) -> None:
    """rows: dicts with item_id/item_vi/item_en/statement_type keys (dupes
    across rows in the same batch are fine, upsert handles it). Raises if an
    item_id is claimed by two different statement types - see StatementItem
    docstring."""
    by_id: dict[str, dict] = {}
    for r in rows:
        existing = by_id.get(r["item_id"])
        if existing and existing["statement_type"] != r["statement_type"]:
            raise ValueError(
                f"item_id {r['item_id']!r} claimed by both "
                f"{existing['statement_type']!r} and {r['statement_type']!r} - "
                "the 'item_id is globally unique' assumption just broke, "
                "statement_type needs to move back into fact_statement_line's key."
            )
        by_id[r["item_id"]] = r
    if not by_id:
        return
    stmt = sqlite_insert(StatementItem).values(list(by_id.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=["item_id"],
        set_={
            "item_vi": stmt.excluded.item_vi,
            "item_en": stmt.excluded.item_en,
            "statement_type": stmt.excluded.statement_type,
        },
    )
    session.execute(stmt)


_symbol_dim_synced_this_process = False


def sync_symbol_dimension(session: Session, force: bool = False) -> int:
    """Populates dim_symbol + dim_sector from the market-wide ticker listing
    (price_access.get_ticker_listing - cached, one call for the whole
    market, not per-symbol). Safe to re-run; upserts.

    Callers that process one symbol at a time (init_financial_history,
    update_latest_quarter) call this every time for standalone safety, since
    a fact row's FK to dim_symbol will fail otherwise. To keep that cheap
    when those are run in a loop over the whole market, the actual listing
    fetch + upsert only happens once per process (get_ticker_listing is also
    day-cached underneath, but re-upserting ~2000 rows per symbol in a
    ~1871-symbol loop still adds up) - pass force=True to bypass this.
    """
    global _symbol_dim_synced_this_process
    if _symbol_dim_synced_this_process and not force:
        return 0

    from market_access.price_access import get_ticker_listing

    listing = get_ticker_listing()

    sector_rows = (
        listing[["icb_code", "icb_name", "icb_level"]].drop_duplicates(subset="icb_code").to_dict("records")
    )
    if sector_rows:
        stmt = sqlite_insert(Sector).values(sector_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["icb_code"],
            set_={"icb_name": stmt.excluded.icb_name, "icb_level": stmt.excluded.icb_level},
        )
        session.execute(stmt)

    # Funds excluded entirely - not operating businesses, don't file the
    # statements this whole schema exists to hold. Canonical sector per
    # symbol = deepest (most specific) ICB level available.
    companies = listing[listing["com_type_code"] != "QU"]
    deepest = companies.sort_values("icb_level").drop_duplicates(subset="symbol", keep="last")
    symbol_rows = [
        {
            "symbol": r.symbol,
            "organ_name": r.organ_name,
            "com_type_code": r.com_type_code,
            "icb_code": r.icb_code,
        }
        for r in deepest.itertuples(index=False)
    ]
    stmt = sqlite_insert(Symbol).values(symbol_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={
            "organ_name": stmt.excluded.organ_name,
            "com_type_code": stmt.excluded.com_type_code,
            "icb_code": stmt.excluded.icb_code,
        },
    )
    session.execute(stmt)
    session.commit()
    _symbol_dim_synced_this_process = True
    return len(symbol_rows)


if __name__ == "__main__":
    print(f"=== DB: {DB_PATH} ===")
    with Session(engine) as session:
        n = sync_symbol_dimension(session)
        print(f"dim_symbol synced: {n} symbols")

        vnm = session.get(Symbol, "VNM")
        vcb = session.get(Symbol, "VCB")
        print(f"VNM: organ_name={vnm.organ_name!r}, is_financial_sector={is_financial_sector(vnm.com_type_code)}")
        print(f"VCB: organ_name={vcb.organ_name!r}, is_financial_sector={is_financial_sector(vcb.com_type_code)}")
        assert is_financial_sector(vnm.com_type_code) is False and is_financial_sector(vcb.com_type_code) is True, (
            "expected VNM excluded=False (normal corp), VCB excluded=True (bank)"
        )

        fund_symbol = session.get(Symbol, "FUEVFVND")  # a well-known ETF ticker
        assert fund_symbol is None, "funds should be excluded from dim_symbol entirely"

        row = period_label_to_row("2026-Q2")
        print(f"period_label_to_row('2026-Q2') = {row}")
        assert row["period_end_date"].isoformat() == "2026-06-30"