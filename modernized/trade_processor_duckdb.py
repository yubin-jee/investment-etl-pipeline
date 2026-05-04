"""Trade Processor - DuckDB Implementation"""

import glob
import time
import tracemalloc

import duckdb


VALID_BROKERS = ("GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS")


def load_trades(file_path: str) -> duckdb.DuckDBPyRelation:
    rel = duckdb.sql(f"""
        SELECT
            TRADE_ID AS trade_id,
            ACCT_NUM AS account,
            TICKER AS ticker,
            SIDE AS side,
            TRY_CAST(QTY AS INTEGER) AS quantity,
            TRY_CAST(PRICE AS DOUBLE) AS price,
            TRADE_DATE AS trade_date,
            SETTLE_DATE AS settle_date,
            BROKER AS broker,
            TRY_CAST(COMMISSION AS DOUBLE) AS commission,
            STATUS AS status
        FROM read_csv_auto('{file_path}', ALL_VARCHAR=TRUE)
        WHERE TRY_CAST(QTY AS INTEGER) IS NOT NULL
          AND TRY_CAST(PRICE AS DOUBLE) IS NOT NULL
    """)
    return rel


def validate_trades(relation: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    initial_count = relation.aggregate("count(*)").fetchone()[0]

    deduped = duckdb.sql("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY trade_id ORDER BY trade_id) AS rn
            FROM relation
        ) WHERE rn = 1
    """).project("* EXCLUDE (rn)")

    filtered = duckdb.sql("""
        SELECT * FROM deduped
        WHERE broker IN ('GOLDMN', 'MRGST', 'JPMC', 'BARCL', 'CITI', 'UBS')
          AND quantity > 0
          AND price > 0
    """)

    result = duckdb.sql("""
        SELECT
            trade_id, account, ticker, side, quantity, price, trade_date,
            CASE WHEN settle_date IS NULL OR settle_date = '' THEN
                CASE WHEN CAST(SUBSTRING(trade_date, 4, 2) AS INTEGER) + 2 > 30 THEN
                    LPAD(CAST(CAST(SUBSTRING(trade_date, 1, 2) AS INTEGER) + 1 AS VARCHAR), 2, '0')
                    || '/'
                    || LPAD(CAST(CAST(SUBSTRING(trade_date, 4, 2) AS INTEGER) + 2 - 30 AS VARCHAR), 2, '0')
                    || '/'
                    || SUBSTRING(trade_date, 7, 4)
                ELSE
                    SUBSTRING(trade_date, 1, 3)
                    || LPAD(CAST(CAST(SUBSTRING(trade_date, 4, 2) AS INTEGER) + 2 AS VARCHAR), 2, '0')
                    || '/'
                    || SUBSTRING(trade_date, 7, 4)
                END
            ELSE settle_date END AS settle_date,
            broker, commission, status
        FROM filtered
    """)

    final_count = result.aggregate("count(*)").fetchone()[0]
    dup_count = initial_count - deduped.aggregate("count(*)").fetchone()[0]
    error_count = initial_count - dup_count - final_count

    print(f"Valid trades: {final_count}")
    print(f"Errors: {error_count}")
    print(f"Duplicates: {dup_count}")
    return result


if __name__ == "__main__":
    files = sorted(glob.glob("legacy_data/trades/daily_trades_*.csv"))
    print(f"Found {len(files)} trade files")

    tracemalloc.start()
    start = time.perf_counter()

    relations = [load_trades(f) for f in files]
    combined = relations[0]
    for r in relations[1:]:
        combined = combined.union(r)
    result = validate_trades(combined)
    result_df = result.df()

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\nExecution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
