-- Mirrors the star schema defined in src/market_access/db.py (SQLAlchemy
-- models Sector/Symbol/StatementItem/Period/StatementLine/Price). This is a
-- read-only online copy for external access (analyst, future web app) - the
-- app itself keeps running on local SQLite, backed by
-- database/financial_reports.sql, as the actual source of truth.

create table dim_period (
    period varchar(10) primary key,
    fiscal_year integer not null,
    fiscal_quarter integer not null,
    period_end_date date not null,
    estimated_publish_date date not null
);

create table dim_sector (
    icb_code varchar(10) primary key,
    icb_name text not null,
    icb_level integer not null
);

create table dim_symbol (
    symbol varchar(20) primary key,
    organ_name text,
    com_type_code varchar(5) not null,
    icb_code varchar(10) references dim_sector(icb_code),
    issue_share double precision,
    dividend_per_share_tsr double precision
);

create table dim_statement_item (
    item_id varchar(20) primary key,
    item_vi text,
    item_en text,
    statement_type varchar(20) not null
);

create table fact_statement_line (
    symbol varchar(20) not null references dim_symbol(symbol),
    period varchar(10) not null references dim_period(period),
    item_id varchar(20) not null references dim_statement_item(item_id),
    value double precision,
    fetched_on varchar(10) not null,
    primary key (symbol, period, item_id)
);

create table fact_price (
    symbol varchar(20) not null references dim_symbol(symbol),
    trade_date date not null,
    open double precision not null,
    high double precision not null,
    low double precision not null,
    close double precision not null,
    volume double precision not null,
    fetched_on varchar(10) not null,
    primary key (symbol, trade_date)
);

create index ix_fact_statement_line_period on fact_statement_line(period);
create index ix_fact_price_trade_date on fact_price(trade_date);
create index ix_dim_symbol_icb_code on dim_symbol(icb_code);
