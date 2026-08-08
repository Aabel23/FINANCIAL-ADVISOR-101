"""
Shared helper for pulling exactly the line items the valuation models need
out of the local star schema (market_access.db) - as trailing-twelve-month
(TTM) sums for flow items (income_statement/cash_flow) or a latest-quarter
snapshot for stock items (balance_sheet). Not a data source of its own -
every value here was already fetched into financial_reports.db by
market_access.financial_report; run that first for a symbol that isn't in
there yet (init_financial_history(symbol)).

TTM-by-summing-4-quarters is deliberate, not multiply-by-4 or take-Q4:
confirmed live against VNM that vnstock's quarterly figures are discrete
per-quarter amounts, not year-to-date cumulative (isa3/net sales stays in
the ~13-19T VND range every quarter rather than resetting each Q1 and
growing through the year) - see market_access/docs for the general
convention. Diluted/weighted-average share count can drift a little
quarter to quarter, so summing quarterly EPS (isa23) into a TTM EPS is a
standard approximation, not exact - noted where used.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_access.db import StatementLine, engine

# Item ids from dim_statement_item (see docs/DATA_MODEL.md for the full list).
EPS = "isa23"  # Lãi cơ bản trên cổ phiếu (VND) - EPS basic, per quarter
NET_INCOME = "isa22"  # Lợi nhuận của Cổ đông của Công ty mẹ - net income attributable to parent
EQUITY = "bsa78"  # Vốn chủ sở hữu - total owner's equity, balance-sheet snapshot
TOTAL_ASSETS = "bsa53"  # TỔNG CỘNG TÀI SẢN - total assets, balance-sheet snapshot
TOTAL_LIABILITIES = "bsa54"  # NỢ PHẢI TRẢ - total liabilities, balance-sheet snapshot
OPERATING_CASH_FLOW = "cfa18"  # Lưu chuyển tiền thuần từ HĐKD - net cash from operating activities
CAPEX = "cfa19"  # Tiền chi mua sắm TSCĐ - purchases of fixed assets (stored negative = outflow)
LOAN_PROCEEDS = "cfa29"  # Tiền thu được các khoản đi vay - proceeds from loans (positive = inflow)
LOAN_REPAYMENT = "cfa30"  # Tiền trả nợ gốc vay - repayment of loans (stored negative = outflow)
DIVIDENDS_PAID = "cfa32"  # Cổ tức, lợi nhuận đã trả cho chủ sở hữu (stored negative = outflow)
REVENUE = "isa3"  # Doanh thu thuần - net sales
CURRENT_ASSETS = "bsa1"  # TÀI SẢN NGẮN HẠN - current assets, balance-sheet snapshot
CURRENT_LIABILITIES = "bsa55"  # Nợ ngắn hạn - current liabilities, balance-sheet snapshot
SHORT_TERM_DEBT = "bsa56"  # Vay ngắn hạn - short-term borrowings, balance-sheet snapshot
LONG_TERM_DEBT = "bsa71"  # Vay dài hạn - long-term borrowings, balance-sheet snapshot


def latest_period(symbol: str, session: Session) -> str:
    stmt = (
        select(StatementLine.period)
        .where(StatementLine.symbol == symbol)
        .order_by(StatementLine.period.desc())
        .limit(1)
    )
    period = session.execute(stmt).scalar_one_or_none()
    if period is None:
        raise ValueError(f"{symbol}: no statement data loaded - run init_financial_history({symbol!r}) first")
    return period


def quarters_window(symbol: str, n: int, session: Session, offset: int = 0) -> list[str]:
    """The n stored periods ending `offset` quarters before the most recent
    one, oldest first. offset=0 (default) is the current trailing window;
    offset=4 is "the 4 quarters before that" - i.e. the same calendar
    quarters one year earlier, for YoY comparisons."""
    stmt = (
        select(StatementLine.period)
        .where(StatementLine.symbol == symbol)
        .distinct()
        .order_by(StatementLine.period.desc())
        .offset(offset)
        .limit(n)
    )
    periods = [row[0] for row in session.execute(stmt).all()]
    if len(periods) < n:
        raise ValueError(f"{symbol}: only {len(periods)}/{n} quarters stored at offset {offset}")
    return sorted(periods)


def trailing_quarters(symbol: str, n: int, session: Session) -> list[str]:
    """The n most recent stored periods for this symbol, oldest first."""
    return quarters_window(symbol, n, session)


def _sum_flow(symbol: str, item_id: str, quarters: list[str], session: Session) -> float:
    stmt = select(StatementLine.value).where(
        StatementLine.symbol == symbol,
        StatementLine.item_id == item_id,
        StatementLine.period.in_(quarters),
    )
    values = [v for (v,) in session.execute(stmt).all() if v is not None]
    if len(values) < len(quarters):
        raise ValueError(f"{symbol}/{item_id}: only {len(values)}/{len(quarters)} quarters have a value")
    return sum(values)


def ttm_flow(symbol: str, item_id: str, session: Session) -> float:
    """Sum of the 4 most recent quarters of a flow (income_statement /
    cash_flow) line item."""
    return _sum_flow(symbol, item_id, trailing_quarters(symbol, 4, session), session)


def ttm_flow_prior_year(symbol: str, item_id: str, session: Session) -> float:
    """TTM sum for the 4 quarters immediately before the current TTM window
    - the prior-year comparable period, for YoY growth. Requires 8 stored
    quarters - vnstock's free-tier ceiling is exactly 8 (confirmed live),
    so this is the deepest YoY comparison possible without accumulating
    more history over time via update_market_financials()."""
    return _sum_flow(symbol, item_id, quarters_window(symbol, 4, session, offset=4), session)


def latest_snapshot(symbol: str, item_id: str, session: Session) -> float:
    """Most recent single-quarter value of a stock (balance_sheet) line
    item - a point-in-time snapshot, never summed across quarters."""
    period = latest_period(symbol, session)
    stmt = select(StatementLine.value).where(
        StatementLine.symbol == symbol, StatementLine.item_id == item_id, StatementLine.period == period
    )
    value = session.execute(stmt).scalar_one_or_none()
    if value is None:
        raise ValueError(f"{symbol}/{item_id}: no value for latest period {period!r}")
    return value


def open_session() -> Session:
    return Session(engine)
