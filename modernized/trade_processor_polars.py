#!/usr/bin/env python
"""
Trade Processor - Polars Implementation
Modernized replacement for legacy_scripts/process_trades.py load_trades() and validate_trades()
"""

import glob
import os
import time
import tracemalloc

import polars as pl

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]

COLUMN_RENAME = {
    "TRADE_ID": "trade_id",
    "ACCT_NUM": "account",
    "TICKER": "ticker",
    "SIDE": "side",
    "QTY": "quantity",
    "PRICE": "price",
    "TRADE_DATE": "trade_date",
    "SETTLE_DATE": "settle_date",
    "BROKER": "broker",
    "COMMISSION": "commission",
    "STATUS": "status",
}


def load_trades(file_path: str) -> pl.DataFrame:
    """Load trades from a CSV file using polars, handling bad numeric values."""
    print(f"Loading trades from {file_path}...")

    df = pl.read_csv(
        file_path,
        schema_overrides={
            "TRADE_ID": pl.Utf8,
            "ACCT_NUM": pl.Utf8,
            "TICKER": pl.Utf8,
            "SIDE": pl.Utf8,
            "QTY": pl.Utf8,
            "PRICE": pl.Utf8,
            "TRADE_DATE": pl.Utf8,
            "SETTLE_DATE": pl.Utf8,
            "BROKER": pl.Utf8,
            "COMMISSION": pl.Utf8,
            "STATUS": pl.Utf8,
        },
    )

    df = df.with_columns(
        pl.col("QTY").cast(pl.Int64, strict=False),
        pl.col("PRICE").cast(pl.Float64, strict=False),
        pl.col("COMMISSION").cast(pl.Float64, strict=False),
    )

    rows_before = df.height
    df = df.filter(pl.col("QTY").is_not_null() & pl.col("PRICE").is_not_null())
    rows_dropped = rows_before - df.height

    df = df.rename(COLUMN_RENAME)

    df = df.with_columns(
        pl.col("settle_date").fill_null(""),
    )

    print(f"Loaded {df.height} trades ({rows_dropped} rows dropped due to parse errors)")
    return df


def validate_trades(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Validate trades: dedup, broker check, qty/price checks, T+2 settle date fill."""
    print("Validating trades...")

    before_dedup = df.height
    df = df.unique(subset=["trade_id"], keep="first")
    duplicate_count = before_dedup - df.height

    before_broker = df.height
    df = df.filter(pl.col("broker").is_in(VALID_BROKERS))
    broker_errors = before_broker - df.height

    before_qty = df.height
    df = df.filter(pl.col("quantity") > 0)
    qty_errors = before_qty - df.height

    before_price = df.height
    df = df.filter(pl.col("price") > 0)
    price_errors = before_price - df.height

    error_count = broker_errors + qty_errors + price_errors

    needs_settle = (pl.col("settle_date") == "") | (pl.col("settle_date").is_null())

    month_expr = pl.col("trade_date").str.split("/").list.get(0).cast(pl.Int32)
    day_expr = pl.col("trade_date").str.split("/").list.get(1).cast(pl.Int32) + 2
    year_expr = pl.col("trade_date").str.split("/").list.get(2)

    adjusted_month = pl.when(day_expr > 30).then(month_expr + 1).otherwise(month_expr)
    adjusted_day = pl.when(day_expr > 30).then(day_expr - 30).otherwise(day_expr)

    computed_settle = (
        adjusted_month.cast(pl.Utf8).str.pad_start(2, "0")
        + pl.lit("/")
        + adjusted_day.cast(pl.Utf8).str.pad_start(2, "0")
        + pl.lit("/")
        + year_expr
    )

    df = df.with_columns(
        pl.when(needs_settle)
        .then(computed_settle)
        .otherwise(pl.col("settle_date"))
        .alias("settle_date")
    )

    valid_count = df.height
    print(f"Valid trades: {valid_count}")
    print(f"Errors: {error_count}")
    print(f"Duplicates: {duplicate_count}")

    stats = {"valid": valid_count, "errors": error_count, "duplicates": duplicate_count}
    return df, stats


if __name__ == "__main__":
    base_dir = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "trades")
    csv_files = sorted(glob.glob(os.path.join(base_dir, "daily_trades_*.csv")))

    if not csv_files:
        print("No trade files found!")
        exit(1)

    print(f"Found {len(csv_files)} trade file(s)")

    tracemalloc.start()
    start = time.perf_counter()

    frames = [load_trades(f) for f in csv_files]
    all_df = pl.concat(frames)

    df, stats = validate_trades(all_df)

    elapsed = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n--- Polars Results ---")
    print(f"Execution time: {elapsed:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {stats['errors']}")
    print(f"Duplicates: {stats['duplicates']}")
