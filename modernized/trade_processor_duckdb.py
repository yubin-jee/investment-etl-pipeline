#!/usr/bin/env python
"""
Trade Processor - DuckDB Implementation
Modernized replacement for legacy_scripts/process_trades.py load_trades() and validate_trades()
"""

import glob
import os
import time
import tracemalloc

import duckdb
import pandas as pd

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]

BROKER_LIST_SQL = "('GOLDMN', 'MRGST', 'JPMC', 'BARCL', 'CITI', 'UBS')"


def load_trades(file_path: str) -> pd.DataFrame:
    """Load trades from a CSV file using DuckDB, handling bad numeric values."""
    print(f"Loading trades from {file_path}...")

    conn = duckdb.connect()

    df = conn.sql(f"""
        SELECT
            TRADE_ID AS trade_id,
            ACCT_NUM AS account,
            TICKER AS ticker,
            SIDE AS side,
            TRY_CAST(QTY AS INTEGER) AS quantity,
            TRY_CAST(PRICE AS DOUBLE) AS price,
            TRADE_DATE AS trade_date,
            COALESCE(SETTLE_DATE, '') AS settle_date,
            BROKER AS broker,
            TRY_CAST(COMMISSION AS DOUBLE) AS commission,
            STATUS AS status
        FROM read_csv_auto('{file_path}', all_varchar=true)
        WHERE TRY_CAST(QTY AS INTEGER) IS NOT NULL
          AND TRY_CAST(PRICE AS DOUBLE) IS NOT NULL
    """).df()

    conn.close()

    rows_loaded = len(df)
    print(f"Loaded {rows_loaded} trades")
    return df


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate trades using DuckDB SQL: dedup, broker/qty/price checks, T+2 fill."""
    print("Validating trades...")

    conn = duckdb.connect()
    conn.register("trades_raw", df)

    initial_count = conn.sql("SELECT COUNT(*) FROM trades_raw").fetchone()[0]

    deduped = conn.sql("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY trade_id ORDER BY trade_id) AS rn
            FROM trades_raw
        ) WHERE rn = 1
    """)
    conn.register("trades_deduped", deduped)
    dedup_count = conn.sql("SELECT COUNT(*) FROM trades_deduped").fetchone()[0]
    duplicate_count = initial_count - dedup_count

    validated = conn.sql(f"""
        SELECT
            trade_id, account, ticker, side, quantity, price,
            trade_date,
            CASE
                WHEN settle_date IS NULL OR settle_date = '' THEN
                    LPAD(
                        CASE
                            WHEN CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 > 30
                            THEN CAST(CAST(SPLIT_PART(trade_date, '/', 1) AS INTEGER) + 1 AS VARCHAR)
                            ELSE LPAD(SPLIT_PART(trade_date, '/', 1), 2, '0')
                        END
                    , 2, '0')
                    || '/'
                    || LPAD(
                        CASE
                            WHEN CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 > 30
                            THEN CAST(CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 - 30 AS VARCHAR)
                            ELSE CAST(CAST(SPLIT_PART(trade_date, '/', 2) AS INTEGER) + 2 AS VARCHAR)
                        END
                    , 2, '0')
                    || '/' || SPLIT_PART(trade_date, '/', 3)
                ELSE settle_date
            END AS settle_date,
            broker, commission, status
        FROM trades_deduped
        WHERE broker IN {BROKER_LIST_SQL}
          AND quantity > 0
          AND price > 0
    """)

    result_df = validated.df()

    valid_count = len(result_df)
    error_count = dedup_count - valid_count

    conn.close()

    print(f"Valid trades: {valid_count}")
    print(f"Errors: {error_count}")
    print(f"Duplicates: {duplicate_count}")

    stats = {"valid": valid_count, "errors": error_count, "duplicates": duplicate_count}
    return result_df, stats


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
    all_df = pd.concat(frames, ignore_index=True)

    df, stats = validate_trades(all_df)

    elapsed = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n--- DuckDB Results ---")
    print(f"Execution time: {elapsed:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
    print(f"Valid trades: {stats['valid']}")
    print(f"Errors: {stats['errors']}")
    print(f"Duplicates: {stats['duplicates']}")
