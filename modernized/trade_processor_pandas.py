"""Trade Processor - Pandas Implementation"""

import glob
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
    df = df.dropna(subset=["QTY", "PRICE"])
    df["QTY"] = df["QTY"].astype(int)
    df = df.rename(columns=COLUMN_RENAME)
    return df


def _compute_settle_date(trade_date: str) -> str:
    parts = trade_date.split("/")
    month = int(parts[0])
    day = int(parts[1]) + 2
    year = int(parts[2])
    if day > 30:
        day = day - 30
        month = month + 1
    return f"{month:02d}/{day:02d}/{year}"


def validate_trades(df: pd.DataFrame) -> pd.DataFrame:
    initial_count = len(df)

    df = df.drop_duplicates(subset="trade_id", keep="first")
    dup_count = initial_count - len(df)

    before = len(df)
    df = df[df["broker"].isin(VALID_BROKERS)]
    invalid_broker = before - len(df)

    before = len(df)
    df = df[df["quantity"] > 0]
    invalid_qty = before - len(df)

    before = len(df)
    df = df[df["price"] > 0]
    invalid_price = before - len(df)

    error_count = invalid_broker + invalid_qty + invalid_price

    mask = df["settle_date"].isna() | (df["settle_date"] == "")
    if mask.any():
        df.loc[mask, "settle_date"] = df.loc[mask, "trade_date"].apply(
            _compute_settle_date
        )

    print(f"Valid trades: {len(df)}")
    print(f"Errors: {error_count}")
    print(f"Duplicates: {dup_count}")
    return df


if __name__ == "__main__":
    files = sorted(glob.glob("legacy_data/trades/daily_trades_*.csv"))
    print(f"Found {len(files)} trade files")

    tracemalloc.start()
    start = time.perf_counter()

    frames = [load_trades(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = validate_trades(df)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\nExecution time: {elapsed_ms:.2f} ms")
    print(f"Peak memory: {peak_mem / 1024 / 1024:.2f} MB")
