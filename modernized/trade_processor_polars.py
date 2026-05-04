#!/usr/bin/env python
"""
Trade Processor - Polars Implementation
Replaces legacy load_trades() and validate_trades() from process_trades.py
"""

import glob
import os
import sys
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


def load_trades(file_path):
    """Load trades from a CSV file using polars.

    Returns
    -------
    tuple[pl.DataFrame, int]
        (DataFrame with renamed columns, number of rows that failed to parse)
    """
    df = pl.read_csv(
        file_path,
        schema_overrides={
            "TRADE_ID": pl.Utf8,
            "ACCT_NUM": pl.Utf8,
            "TICKER": pl.Utf8,
            "SIDE": pl.Utf8,
            "BROKER": pl.Utf8,
            "STATUS": pl.Utf8,
            "QTY": pl.Utf8,
            "PRICE": pl.Utf8,
            "COMMISSION": pl.Utf8,
            "TRADE_DATE": pl.Utf8,
            "SETTLE_DATE": pl.Utf8,
        },
    )

    df = df.with_columns(
        pl.col("QTY").cast(pl.Int64, strict=False),
        pl.col("PRICE").cast(pl.Float64, strict=False),
        pl.col("COMMISSION").cast(pl.Float64, strict=False),
    )

    error_mask = pl.col("PRICE").is_null() | pl.col("QTY").is_null()
    load_errors = int(df.filter(error_mask).height)
    df = df.filter(~error_mask)

    df = df.rename(COLUMN_RENAME)

    print(f"Loaded {df.height} trades from {file_path} ({load_errors} load errors)")
    return df, load_errors


def validate_trades(df):
    """Validate trades applying the same rules as the legacy code.

    Returns
    -------
    tuple[pl.DataFrame, dict]
        (valid DataFrame, stats dict with keys: valid, errors, duplicates)
    """
    # Dedup
    before_dedup = df.height
    df = df.unique(subset=["trade_id"], keep="first", maintain_order=True)
    duplicate_count = before_dedup - df.height

    # Broker filter
    before = df.height
    df = df.filter(pl.col("broker").is_in(VALID_BROKERS))
    invalid_broker = before - df.height

    # Quantity > 0
    before = df.height
    df = df.filter(pl.col("quantity") > 0)
    invalid_qty = before - df.height

    # Price > 0
    before = df.height
    df = df.filter(pl.col("price") > 0)
    invalid_price = before - df.height

    error_count = invalid_broker + invalid_qty + invalid_price

    # Fill missing settle_date with naive T+2 using vectorized expressions
    month_expr = pl.col("trade_date").str.split("/").list.get(0).cast(pl.Int32)
    day_raw = pl.col("trade_date").str.split("/").list.get(1).cast(pl.Int32) + 2
    year_expr = pl.col("trade_date").str.split("/").list.get(2)

    adjusted_day = pl.when(day_raw > 30).then(day_raw - 30).otherwise(day_raw)
    adjusted_month = pl.when(day_raw > 30).then(month_expr + 1).otherwise(month_expr)

    computed_settle = (
        adjusted_month.cast(pl.Utf8).str.zfill(2)
        + pl.lit("/")
        + adjusted_day.cast(pl.Utf8).str.zfill(2)
        + pl.lit("/")
        + year_expr
    )

    df = df.with_columns(
        pl.when(pl.col("settle_date").is_null() | (pl.col("settle_date") == ""))
        .then(computed_settle)
        .otherwise(pl.col("settle_date"))
        .alias("settle_date")
    )

    stats = {"valid": df.height, "errors": error_count, "duplicates": duplicate_count}

    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {stats['errors']}")
    print(f"Duplicates: {stats['duplicates']}")

    return df, stats


if __name__ == "__main__":
    trade_dir = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "trades")
    csv_files = sorted(glob.glob(os.path.join(trade_dir, "daily_trades_*.csv")))

    if not csv_files:
        print("No trade files found!")
        sys.exit(1)

    tracemalloc.start()
    start = time.perf_counter()

    total_load_errors = 0
    dfs = []
    for f in csv_files:
        df, load_errors = load_trades(f)
        dfs.append(df)
        total_load_errors += load_errors

    combined = pl.concat(dfs)
    valid_df, stats = validate_trades(combined)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak_memory / (1024 * 1024)

    total_errors = stats["errors"] + total_load_errors

    print(f"\n--- Polars Results ---")
    print(f"Execution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mb:.4f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {total_errors}")
    print(f"Duplicates: {stats['duplicates']}")
