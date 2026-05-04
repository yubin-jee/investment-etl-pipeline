"""Trade Processor - Polars Implementation"""

import glob
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
    df = pl.read_csv(
        file_path,
        dtypes={
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
        pl.col("QTY").cast(pl.Int64, strict=False).alias("QTY"),
        pl.col("PRICE").cast(pl.Float64, strict=False).alias("PRICE"),
        pl.col("COMMISSION").cast(pl.Float64, strict=False).alias("COMMISSION"),
    )
    df = df.filter(pl.col("QTY").is_not_null() & pl.col("PRICE").is_not_null())
    df = df.rename(COLUMN_RENAME)
    return df


def _compute_t_plus_2(trade_date: str) -> str:
    parts = trade_date.split("/")
    month = int(parts[0])
    day = int(parts[1]) + 2
    year = int(parts[2])
    if day > 30:
        day = day - 30
        month = month + 1
    return f"{month:02d}/{day:02d}/{year}"


def validate_trades(df: pl.DataFrame) -> pl.DataFrame:
    initial_count = df.height

    df = df.unique(subset=["trade_id"], keep="first")
    dup_count = initial_count - df.height

    before = df.height
    df = df.filter(pl.col("broker").is_in(VALID_BROKERS))
    invalid_broker = before - df.height

    before = df.height
    df = df.filter(pl.col("quantity") > 0)
    invalid_qty = before - df.height

    before = df.height
    df = df.filter(pl.col("price") > 0)
    invalid_price = before - df.height

    error_count = invalid_broker + invalid_qty + invalid_price

    needs_settle = (pl.col("settle_date").is_null()) | (pl.col("settle_date") == "")
    df = df.with_columns(
        pl.when(needs_settle)
        .then(pl.col("trade_date").map_elements(_compute_t_plus_2, return_dtype=pl.Utf8))
        .otherwise(pl.col("settle_date"))
        .alias("settle_date")
    )

    print(f"Valid trades: {df.height}")
    print(f"Errors: {error_count}")
    print(f"Duplicates: {dup_count}")
    return df


if __name__ == "__main__":
    files = sorted(glob.glob("legacy_data/trades/daily_trades_*.csv"))
    print(f"Found {len(files)} trade files")

    tracemalloc.start()
    start = time.perf_counter()

    frames = [load_trades(f) for f in files]
    df = pl.concat(frames)
    df = validate_trades(df)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\nExecution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
