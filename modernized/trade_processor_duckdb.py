#!/usr/bin/env python
"""
Trade Processor - DuckDB Implementation
Replaces legacy load_trades() and validate_trades() from process_trades.py
"""

import glob
import os
import sys
import time
import tracemalloc

import duckdb
import pandas as pd

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


def load_trades(file_path):
    """Load trades from a CSV file using DuckDB.

    Returns
    -------
    tuple[pd.DataFrame, int]
        (DataFrame with renamed columns, number of rows that failed to parse)
    """
    conn = duckdb.connect()

    total = conn.execute(
        "SELECT COUNT(*) FROM read_csv_auto(?, ALL_VARCHAR=true)", [file_path]
    ).fetchone()[0]

    df = conn.execute(
        """
        SELECT
            TRADE_ID   AS trade_id,
            ACCT_NUM   AS account,
            TICKER     AS ticker,
            SIDE       AS side,
            TRY_CAST(QTY AS INTEGER)      AS quantity,
            TRY_CAST(PRICE AS DOUBLE)     AS price,
            TRADE_DATE AS trade_date,
            SETTLE_DATE AS settle_date,
            BROKER     AS broker,
            TRY_CAST(COMMISSION AS DOUBLE) AS commission,
            STATUS     AS status
        FROM read_csv_auto(?, ALL_VARCHAR=true)
        WHERE TRY_CAST(PRICE AS DOUBLE) IS NOT NULL
          AND TRY_CAST(QTY AS INTEGER) IS NOT NULL
        """,
        [file_path],
    ).df()

    load_errors = total - len(df)
    conn.close()

    print(f"Loaded {len(df)} trades from {file_path} ({load_errors} load errors)")
    return df, load_errors


def validate_trades(df):
    """Validate trades applying the same rules as the legacy code.

    All logic is expressed in SQL via DuckDB.

    Returns
    -------
    tuple[pd.DataFrame, dict]
        (valid DataFrame, stats dict with keys: valid, errors, duplicates)
    """
    conn = duckdb.connect()
    conn.register("trades_raw", df)

    initial_count = len(df)

    broker_list = ", ".join(f"'{b}'" for b in VALID_BROKERS)

    result = conn.execute(
        f"""
        WITH numbered AS (
            SELECT *, ROW_NUMBER() OVER () AS _orig_order
            FROM trades_raw
        ),
        deduped AS (
            SELECT *
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY trade_id ORDER BY _orig_order
                       ) AS _dedup_rn
                FROM numbered
            ) sub
            WHERE _dedup_rn = 1
        ),
        valid AS (
            SELECT *
            FROM deduped
            WHERE broker IN ({broker_list})
              AND quantity > 0
              AND price > 0
        ),
        with_settle AS (
            SELECT
                trade_id, account, ticker, side, quantity, price,
                trade_date,
                CASE
                    WHEN settle_date IS NULL OR settle_date = '' THEN
                        LPAD(CAST(
                            CASE
                                WHEN CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 > 30
                                THEN CAST(SPLIT_PART(trade_date, '/', 1) AS INTEGER) + 1
                                ELSE CAST(SPLIT_PART(trade_date, '/', 1) AS INTEGER)
                            END AS VARCHAR), 2, '0')
                        || '/'
                        || LPAD(CAST(
                            CASE
                                WHEN CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 > 30
                                THEN CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 - 30
                                ELSE CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2
                            END AS VARCHAR), 2, '0')
                        || '/'
                        || SPLIT_PART(trade_date, '/', 3)
                    ELSE settle_date
                END AS settle_date,
                broker, commission, status
            FROM valid
        )
        SELECT * FROM with_settle
        """
    ).df()

    # Compute stats
    dedup_count_row = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT *, ROW_NUMBER() OVER (PARTITION BY trade_id) AS rn"
        "  FROM trades_raw"
        ") sub WHERE rn = 1"
    ).fetchone()
    unique_count = dedup_count_row[0]
    duplicate_count = initial_count - unique_count

    # Validation errors = unique rows minus valid rows (before settle fix)
    valid_before_settle = conn.execute(
        f"""
        WITH deduped AS (
            SELECT * FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY trade_id) AS rn
                FROM trades_raw
            ) sub WHERE rn = 1
        )
        SELECT COUNT(*) FROM deduped
        WHERE broker IN ({broker_list})
          AND quantity > 0
          AND price > 0
        """
    ).fetchone()[0]
    error_count = unique_count - valid_before_settle

    conn.close()

    stats = {"valid": len(result), "errors": error_count, "duplicates": duplicate_count}

    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {stats['errors']}")
    print(f"Duplicates: {stats['duplicates']}")

    return result, stats


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

    print(f"\n--- DuckDB Results ---")
    print(f"Execution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mb:.4f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {total_errors}")
    print(f"Duplicates: {stats['duplicates']}")
