"""
Establishes read access to Vietnam market data (HOSE/HNX/UPCOM) via the `vnstock`
library, and persists what it fetches into the shared local DB (market_access.db) -
same convention as financial_report.py. Nothing outside market_access/ should call
vnstock directly: valuation/ and regression/ read prices and company snapshot data
(current price, shares outstanding, trailing dividend) from the DB only, via
valuation._inputs. The functions here are what keeps that DB up to date.

Two kinds of local storage:
  - fact_price (market_access.db.Price) - permanent, accumulating daily OHLCV
    history. sync_price_history() only ever asks vnstock for the days since the
    last stored row (or a fixed lookback on first run) - cheap enough (1 call/
    symbol) to run daily, unlike financial_report.py's statement backfill.
  - dim_symbol.issue_share / dividend_per_share_tsr - type-1 (overwrite) snapshot
    fields, refreshed by sync_company_snapshot() from vnstock's company overview
    call. "Current price" is NOT stored here - it's always the latest fact_price
    row for the symbol (see valuation._inputs.current_price).

Refresh cadence, deliberately split by how often the underlying data actually
changes: run update_market_prices() (this file) daily - price moves every
trading day, and it's only 2 API calls/symbol so a full-market daily pass is
cheap. Run update_market_financials() (financial_report.py) quarterly -
statements are only filed once a quarter, so anything more frequent would just
re-fetch the same numbers. Both are manual (you run them yourself, watch the
output), same convention as the rest of this project - see README.md.

get_ticker_listing/get_stock_universe are unchanged from before: they already feed
dim_symbol/dim_sector via db.sync_symbol_dimension, so the market-wide listing was
already DB-backed - only the per-symbol price/overview calls needed to move.
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import vnstock
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

# Vietnamese company/sector names crash print() under the default Windows console
# codepage unless stdout is forced to UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# Confirmed working against this vnstock version during earlier exploration.
# Alternatives exposed by vnstock: "TCBS", "MSN", "DNSE".
DATA_SOURCE = "VCI"

# com_type_code values seen in the listing: CT=company (1781), QU=investment
# fund (171), CK=securities firm (45), NH=bank (31), BH=insurer (14). Funds
# are excluded from the universe - they don't file financial statements the
# way an operating company/bank/insurer/broker does, so P/E, ROE etc. don't
# apply the same way and they'd corrupt any market-wide ranking.
_NON_COMPANY_TYPE_CODES = {"QU"}

# Per-day file cache so a sync run that gets interrupted and re-started the same
# day doesn't re-hit vnstock for symbols it already fetched. Gitignored
# (data_cache/); a cached file older than today is treated as stale. This sits
# below the DB layer, not instead of it - the DB is what everything else reads.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"

# How far back to backfill on a symbol's first-ever price sync. 5 years matches
# this project's 5-year investment horizon - no reason to carry more.
_INIT_LOOKBACK_DAYS = 5 * 365

# Free-tier rate limit is 60 req/min (see financial_report.py); one sync pass
# costs 2 calls/symbol (price history + company overview).
_TARGET_REQUESTS_PER_MINUTE = 50
_CALLS_PER_SYMBOL = 2
_SECONDS_PER_SYMBOL = 60 / (_TARGET_REQUESTS_PER_MINUTE / _CALLS_PER_SYMBOL)


def _read_cache(key: str) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{key}.parquet"
    if not path.exists():
        return None
    if date.fromtimestamp(path.stat().st_mtime) != date.today():
        return None
    return pd.read_parquet(path)


def _write_cache(key: str, df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_DIR / f"{key}.parquet")


def _cached(key: str, fetch, use_cache: bool) -> pd.DataFrame:
    if use_cache:
        cached = _read_cache(key)
        if cached is not None:
            return cached
    df = fetch()
    if use_cache:
        _write_cache(key, df)
    return df


def get_ticker_listing(use_cache: bool = True):
    """All listed tickers with sector (ICB) classification - one row per symbol
    per ICB hierarchy level, so the same symbol can appear more than once. Feeds
    dim_symbol/dim_sector via db.sync_symbol_dimension - not called from
    valuation/regression code directly."""
    return _cached(
        "ticker_listing",
        lambda: vnstock.Listing(source=DATA_SOURCE).symbols_by_industries(),
        use_cache,
    )


def _fetch_price_history(symbol: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """Raw vnstock call: daily OHLCV for one symbol, start/end as 'YYYY-MM-DD'.
    open/high/low/close normalized to raw VND (vnstock's history endpoint returns
    thousands of VND). Internal - sync_price_history() is what callers outside
    this module should use; this only talks to vnstock, it doesn't touch the DB."""

    def fetch():
        quote = vnstock.Quote(symbol=symbol, source=DATA_SOURCE)
        df = quote.history(start=start, end=end, interval="1D")
        df[["open", "high", "low", "close"]] *= 1000
        return df

    return _cached(f"price_history_{symbol}_{start}_{end}", fetch, use_cache)


def _fetch_company_overview(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """Raw vnstock call: snapshot info for one symbol (current_price, market_cap,
    issue_share, dividend_per_share_tsr, sector, is_bank, listing_date, ...).
    Internal - sync_company_snapshot() is what callers outside this module
    should use."""
    return _cached(
        f"company_overview_{symbol}",
        lambda: vnstock.Company(symbol=symbol, source=DATA_SOURCE).overview(),
        use_cache,
    )


def get_stock_universe(use_cache: bool = True) -> list[str]:
    """Every tradeable-company symbol in the market, deduped and with
    investment funds excluded (see _NON_COMPANY_TYPE_CODES). This is the
    universe financial_report.py/price_access.py loop over for market-wide
    collection."""
    listing = get_ticker_listing(use_cache=use_cache)
    companies = listing[~listing["com_type_code"].isin(_NON_COMPANY_TYPE_CODES)]
    return sorted(companies["symbol"].unique().tolist())


# ---- DB sync: fact_price + dim_symbol snapshot fields ---------------------


def _last_price_date(symbol: str, session: Session) -> date | None:
    from market_access.db import Price

    stmt = select(Price.trade_date).where(Price.symbol == symbol).order_by(Price.trade_date.desc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def _upsert_prices(symbol: str, df: pd.DataFrame, session: Session) -> int:
    from market_access.db import Price

    if df.empty:
        return 0
    fetched_on = date.today().isoformat()
    rows = [
        {
            "symbol": symbol,
            "trade_date": row.time.date(),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
            "fetched_on": fetched_on,
        }
        for row in df.itertuples(index=False)
    ]
    stmt = sqlite_insert(Price).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "trade_date"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "fetched_on": stmt.excluded.fetched_on,
        },
    )
    session.execute(stmt)
    session.commit()
    return len(rows)


def sync_price_history(symbol: str, session: Session, start: str | None = None) -> bool:
    """Fetches whatever daily bars are new since the last stored row for
    `symbol` (or the last _INIT_LOOKBACK_DAYS if nothing is stored yet) and
    upserts them into fact_price. Returns True if it hit the API, False if
    already up to date as of yesterday's close (today's bar may not exist yet
    intraday, so "up to date" means through yesterday)."""
    today = date.today()
    last = _last_price_date(symbol, session)
    if start is not None:
        fetch_start = date.fromisoformat(start)
    elif last is not None:
        fetch_start = last + timedelta(days=1)
    else:
        fetch_start = today - timedelta(days=_INIT_LOOKBACK_DAYS)

    if fetch_start > today - timedelta(days=1):
        return False  # already caught up through yesterday

    df = _fetch_price_history(symbol, start=fetch_start.isoformat(), end=today.isoformat(), use_cache=False)
    _upsert_prices(symbol, df, session)
    return True


def sync_company_snapshot(symbol: str, session: Session) -> None:
    """Refreshes dim_symbol.issue_share/dividend_per_share_tsr for `symbol`
    from vnstock's company overview call. Type-1 overwrite - always the
    latest snapshot, no history kept (see db.Symbol docstring)."""
    from sqlalchemy import update

    from market_access.db import Symbol

    overview = _fetch_company_overview(symbol, use_cache=False)
    issue_share = float(overview["issue_share"].iloc[0])
    dividend_per_share_tsr = float(overview["dividend_per_share_tsr"].iloc[0])
    # Plain UPDATE, not upsert: dim_symbol.com_type_code/organ_name/icb_code
    # only come from sync_symbol_dimension (the market-wide listing), which
    # this function doesn't have data for - an upsert's INSERT branch would
    # fail dim_symbol's NOT NULL com_type_code before ON CONFLICT even gets a
    # chance to fire. Requires the row to already exist, same FK-dependency
    # convention as fact_statement_line.
    result = session.execute(
        update(Symbol)
        .where(Symbol.symbol == symbol)
        .values(issue_share=issue_share, dividend_per_share_tsr=dividend_per_share_tsr)
    )
    if result.rowcount == 0:
        raise ValueError(f"{symbol}: not in dim_symbol yet - run market_access.db.sync_symbol_dimension first")
    session.commit()


def init_symbol_market_data(symbol: str) -> None:
    """Full first-time sync for one symbol: dim_symbol must already have this
    symbol (sync_symbol_dimension), then backfills _INIT_LOOKBACK_DAYS of
    price history and the current company snapshot."""
    from market_access.db import engine as _engine
    from market_access.db import sync_symbol_dimension

    with Session(_engine) as session:
        sync_symbol_dimension(session)
        sync_price_history(symbol, session)
        sync_company_snapshot(symbol, session)


def update_symbol_market_data(symbol: str) -> bool:
    """Incremental refresh for one symbol: new price bars since last sync,
    plus a fresh company snapshot (cheap - one call, no skip logic needed
    the way statements have, since it's always "the current snapshot").
    Returns True if new price bars were actually fetched."""
    from market_access.db import engine as _engine
    from market_access.db import sync_symbol_dimension

    with Session(_engine) as session:
        # Cheap after the first call in-process (sync_symbol_dimension only
        # does real work once per process) - see market_access/db.py.
        sync_symbol_dimension(session)
        fetched = sync_price_history(symbol, session)
        sync_company_snapshot(symbol, session)
        return fetched


def init_market_prices(symbols: list[str] | None = None) -> None:
    """Backfills price + snapshot data for the whole market (or a given
    symbol list). Every symbol costs 2 API calls on a first run, throttled to
    stay under the free-tier rate limit."""
    symbols = symbols or get_stock_universe()
    for i, symbol in enumerate(symbols, 1):
        start = time.monotonic()
        try:
            init_symbol_market_data(symbol)
            print(f"[{i}/{len(symbols)}] {symbol}: OK")
        except Exception as e:
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED - {e}")
        elapsed = time.monotonic() - start
        if elapsed < _SECONDS_PER_SYMBOL:
            time.sleep(_SECONDS_PER_SYMBOL - elapsed)


def update_market_prices(symbols: list[str] | None = None) -> None:
    """The manual, daily refresh for the whole market: pulls every price bar
    since each symbol's last stored date plus a fresh company snapshot.
    Meant to be run once a trading day (python -m market_access.price_access
    all) - unlike financial_report.update_market_financials (quarterly,
    since statements don't change more often than that), price genuinely
    moves every day, and a full-market pass is still cheap (2 calls/symbol,
    ~1871 symbols, throttled to the free-tier rate limit). Run it yourself,
    watch it work through the universe, check the printed summary."""
    symbols = symbols or get_stock_universe()
    fetched = failed = 0
    for i, symbol in enumerate(symbols, 1):
        start = time.monotonic()
        try:
            got_new = update_symbol_market_data(symbol)
            fetched += int(got_new)
            print(f"[{i}/{len(symbols)}] {symbol}: {'fetched' if got_new else 'up to date'}")
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED - {e}")
        elapsed = time.monotonic() - start
        if elapsed < _SECONDS_PER_SYMBOL:
            time.sleep(_SECONDS_PER_SYMBOL - elapsed)
    print(f"\ndone: {fetched} symbols had new price bars, {failed} failed, {len(symbols)} total")


def _run_for_symbol(symbol: str) -> None:
    """Real single-symbol usage: python -m market_access.price_access FPT"""
    from market_access.db import Price, Symbol, engine

    fetched = update_symbol_market_data(symbol)
    with Session(engine) as session:
        rows = session.execute(select(Price).where(Price.symbol == symbol).order_by(Price.trade_date)).all()
        if not rows:
            print(f"{symbol}: no price data found - check the symbol is a real, non-fund ticker")
            return
        symbol_row = session.get(Symbol, symbol)
        print(
            f"{symbol}: hit the API for new price bars this run: {fetched}. "
            f"{len(rows)} price rows stored, {rows[0][0].trade_date} .. {rows[-1][0].trade_date}"
        )
        print(f"issue_share={symbol_row.issue_share:,.0f}, dividend_per_share_tsr={symbol_row.dividend_per_share_tsr:,.0f}")


def _run_for_all() -> None:
    """Whole-market usage: python -m market_access.price_access all"""
    update_market_prices()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].upper()
        if arg == "ALL":
            _run_for_all()
        else:
            _run_for_symbol(arg)
        raise SystemExit(0)

    print("=== 1. Ticker listing (market-wide access) ===")
    listing_df = get_ticker_listing()
    print(f"{len(listing_df)} rows, {listing_df['symbol'].nunique()} unique symbols")
    print(listing_df.head(10))

    print("\n=== 2. Init market data for VNM (price history + company snapshot -> DB) ===")
    init_symbol_market_data("VNM")

    from market_access.db import Price, Symbol, engine

    with Session(engine) as session:
        rows = session.execute(select(Price).where(Price.symbol == "VNM").order_by(Price.trade_date)).all()
        print(f"{len(rows)} price rows stored for VNM, {rows[0][0].trade_date} .. {rows[-1][0].trade_date}")
        vnm = session.get(Symbol, "VNM")
        print(f"issue_share={vnm.issue_share:,.0f}, dividend_per_share_tsr={vnm.dividend_per_share_tsr:,.0f}")

        print("\n=== 3. Re-run should fetch nothing new (already caught up through yesterday) ===")
        fetched_again = update_symbol_market_data("VNM")
        print(f"hit the API for new price bars: {fetched_again} (expected False)")
        assert fetched_again is False, "expected a skip since VNM was just fully synced"

    print("\n=== 4. Stock universe (funds excluded) ===")
    universe = get_stock_universe()
    print(f"{len(universe)} symbols, e.g. {universe[:10]}")
    assert "VNM" in universe and not any(
        s in universe for s in listing_df.loc[listing_df["com_type_code"] == "QU", "symbol"].unique()[:5]
    ), "universe filter let a fund through or dropped a real company"