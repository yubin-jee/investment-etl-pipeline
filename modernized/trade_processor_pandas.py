#!/usr/bin/env python
"""
Trade Processor - Pandas Implementation
Replaces legacy load_trades() and validate_trades() from process_trades.py
"""

import glob
import os
import sys
import time
import tracemalloc

import pandas as pd

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


def _compute_t_plus_2(trade_date_str):
    """Naive T+2 settle date from trade_date string (MM/DD/YYYY).

    Replicates the original month-rollover logic: if day > 30,
    subtract 30 and increment month.
    """
    parts = trade_date_str.split("/")
    month = int(parts[0])
    day = int(parts[1]) + 2
    year = int(parts[2])
    if day > 30:
        day = day - 30
        month = month + 1
    return f"{month:02d}/{day:02d}/{year}"


def load_trades(file_path):
    """Load trades from a CSV file.

    Returns
    -------
    tuple[pd.DataFrame, int]
        (DataFrame with renamed columns, number of rows that failed to parse)
    """
    df = pd.read_csv(
        file_path,
        dtype={
            "TRADE_ID": str,
            "ACCT_NUM": str,
            "TICKER": str,
            "SIDE": str,
            "BROKER": str,
            "STATUS": str,
        },
    )

    df["QTY"] = pd.to_numeric(df["QTY"], errors="coerce")
    df["PRICE"] = pd.to_numeric(df["PRICE"], errors="coerce")
    df["COMMISSION"] = pd.to_numeric(df["COMMISSION"], errors="coerce")

    error_mask = df["PRICE"].isna() | df["QTY"].isna()
    load_errors = int(error_mask.sum())
    df = df.dropna(subset=["PRICE", "QTY"])
    df["QTY"] = df["QTY"].astype(int)

    df = df.rename(columns=COLUMN_RENAME)

    print(f"Loaded {len(df)} trades from {file_path} ({load_errors} load errors)")
    return df, load_errors


def validate_trades(df):
    """Validate trades applying the same rules as the legacy code.

    Returns
    -------
    tuple[pd.DataFrame, dict]
        (valid DataFrame, stats dict with keys: valid, errors, duplicates)
    """
    # Dedup
    before_dedup = len(df)
    df = df.drop_duplicates(subset="trade_id", keep="first")
    duplicate_count = before_dedup - len(df)

    # Broker filter
    broker_mask = df["broker"].isin(VALID_BROKERS)
    invalid_broker = int((~broker_mask).sum())
    df = df[broker_mask]

    # Quantity > 0
    qty_mask = df["quantity"] > 0
    invalid_qty = int((~qty_mask).sum())
    df = df[qty_mask]

    # Price > 0
    price_mask = df["price"] > 0
    invalid_price = int((~price_mask).sum())
    df = df[price_mask]

    error_count = invalid_broker + invalid_qty + invalid_price

    # Fill missing settle_date with naive T+2
    empty_settle = df["settle_date"].isna() | (df["settle_date"] == "")
    if empty_settle.any():
        df = df.copy()
        df.loc[empty_settle, "settle_date"] = df.loc[
            empty_settle, "trade_date"
        ].apply(_compute_t_plus_2)

    stats = {"valid": len(df), "errors": error_count, "duplicates": duplicate_count}

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

    combined = pd.concat(dfs, ignore_index=True)
    valid_df, stats = validate_trades(combined)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak_memory / (1024 * 1024)

    total_errors = stats["errors"] + total_load_errors

    print(f"\n--- Pandas Results ---")
    print(f"Execution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mb:.4f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {total_errors}")
    print(f"Duplicates: {stats['duplicates']}")
