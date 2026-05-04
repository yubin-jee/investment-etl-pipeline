#!/usr/bin/env python
"""
Trade Processor - Pandas Implementation
Modernized replacement for legacy_scripts/process_trades.py load_trades() and validate_trades()
"""

import glob
import os
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


def load_trades(file_path: str) -> pd.DataFrame:
    """Load trades from a CSV file, coercing bad numeric values and dropping failures."""
    print(f"Loading trades from {file_path}...")

    df = pd.read_csv(
        file_path,
        dtype={
            "TRADE_ID": str,
            "ACCT_NUM": str,
            "TICKER": str,
            "SIDE": str,
            "BROKER": str,
            "STATUS": str,
            "TRADE_DATE": str,
            "SETTLE_DATE": str,
        },
    )

    df["QTY"] = pd.to_numeric(df["QTY"], errors="coerce")
    df["PRICE"] = pd.to_numeric(df["PRICE"], errors="coerce")
    df["COMMISSION"] = pd.to_numeric(df["COMMISSION"], errors="coerce")

    rows_before = len(df)
    df = df.dropna(subset=["QTY", "PRICE"])
    rows_dropped = rows_before - len(df)

    df["QTY"] = df["QTY"].astype(int)

    df = df.rename(columns=COLUMN_RENAME)

    df["settle_date"] = df["settle_date"].fillna("")

    print(f"Loaded {len(df)} trades ({rows_dropped} rows dropped due to parse errors)")
    return df


def _compute_t2(trade_date: str) -> str:
    """Replicate the legacy naive T+2 settle date calculation."""
    parts = trade_date.split("/")
    month = int(parts[0])
    day = int(parts[1]) + 2
    year = int(parts[2])
    if day > 30:
        day = day - 30
        month = month + 1
    return f"{month:02d}/{day:02d}/{year}"


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate trades: dedup, broker check, qty/price checks, T+2 settle date fill."""
    print("Validating trades...")

    initial_count = len(df)

    before_dedup = len(df)
    df = df.drop_duplicates(subset="trade_id", keep="first")
    duplicate_count = before_dedup - len(df)

    before_broker = len(df)
    df = df[df["broker"].isin(VALID_BROKERS)]
    broker_errors = before_broker - len(df)

    before_qty = len(df)
    df = df[df["quantity"] > 0]
    qty_errors = before_qty - len(df)

    before_price = len(df)
    df = df[df["price"] > 0]
    price_errors = before_price - len(df)

    error_count = broker_errors + qty_errors + price_errors

    mask = (df["settle_date"] == "") | (df["settle_date"].isna())
    if mask.any():
        df.loc[mask, "settle_date"] = df.loc[mask, "trade_date"].apply(_compute_t2)

    valid_count = len(df)
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

    all_df = pd.DataFrame()
    load_errors = 0
    for f in csv_files:
        loaded = load_trades(f)
        load_errors += 0  # parse errors already handled by dropna
        all_df = pd.concat([all_df, loaded], ignore_index=True)

    df, stats = validate_trades(all_df)

    elapsed = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n--- Pandas Results ---")
    print(f"Execution time: {elapsed:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {stats['errors']}")
    print(f"Duplicates: {stats['duplicates']}")
