"""
Establishes read access to Vietnam market data (HOSE/HNX/UPCOM) via the `vnstock`
library. Run this file directly to verify the connection is alive and pulling real
data - nothing here is faked or falls back to synthetic data on failure; if a call
fails, it raises, and you'll see it.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import vnstock

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

# Per-day file cache so repeated runs in the same session don't re-hit vnstock.
# Gitignored (data_cache/); a cached file older than today is treated as stale.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"


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
    per ICB hierarchy level, so the same symbol can appear more than once."""
    return _cached(
        "ticker_listing",
        lambda: vnstock.Listing(source=DATA_SOURCE).symbols_by_industries(),
        use_cache,
    )


def get_price_history(symbol: str, start: str, end: str, use_cache: bool = True):
    """Daily OHLCV history for one symbol. start/end as 'YYYY-MM-DD'.
    open/high/low/close are normalized to raw VND (vnstock's history endpoint
    returns thousands of VND; multiplying by 1000 makes it consistent with the
    raw-VND figures get_company_overview returns, e.g. current_price)."""

    def fetch():
        quote = vnstock.Quote(symbol=symbol, source=DATA_SOURCE)
        df = quote.history(start=start, end=end, interval="1D")
        df[["open", "high", "low", "close"]] *= 1000
        return df

    return _cached(f"price_history_{symbol}_{start}_{end}", fetch, use_cache)


def get_company_overview(symbol: str, use_cache: bool = True):
    """Snapshot info for one symbol: current_price (raw VND), market_cap,
    issue_share (shares outstanding), sector, is_bank, listing_date, etc."""
    return _cached(
        f"company_overview_{symbol}",
        lambda: vnstock.Company(symbol=symbol, source=DATA_SOURCE).overview(),
        use_cache,
    )


def get_stock_universe(use_cache: bool = True) -> list[str]:
    """Every tradeable-company symbol in the market, deduped and with
    investment funds excluded (see _NON_COMPANY_TYPE_CODES). This is the
    universe financial_report.py loops over for market-wide collection."""
    listing = get_ticker_listing(use_cache=use_cache)
    companies = listing[~listing["com_type_code"].isin(_NON_COMPANY_TYPE_CODES)]
    return sorted(companies["symbol"].unique().tolist())


if __name__ == "__main__":
    print("=== 1. Ticker listing (market-wide access) ===")
    listing_df = get_ticker_listing()
    print(f"{len(listing_df)} rows, {listing_df['symbol'].nunique()} unique symbols")
    print(listing_df.head(10))

    print("\n=== 2. Price history for VNM (single-stock access) ===")
    prices_df = get_price_history("VNM", start="2026-07-01", end="2026-08-08")
    print(prices_df)

    print("\n=== 3. Company overview for VNM ===")
    overview = get_company_overview("VNM")
    print(overview)
    print(
        f"unit check: overview current_price={overview['current_price'].iloc[0]} vs "
        f"latest normalized history close={prices_df['close'].iloc[-1]} (should be close)"
    )

    print("\n=== 4. Stock universe (funds excluded) ===")
    universe = get_stock_universe()
    print(f"{len(universe)} symbols, e.g. {universe[:10]}")
    assert "VNM" in universe and not any(
        s in universe for s in listing_df.loc[listing_df["com_type_code"] == "QU", "symbol"].unique()[:5]
    ), "universe filter let a fund through or dropped a real company"
