"""Pandas-based ingestion for trade CSV and fixed-width counterparty files.

Replaces the legacy positional-index CSV reader and manual fixed-width
parsing with robust, dtype-aware pandas operations.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Column names matching the daily trade CSV header
TRADE_CSV_COLUMNS = [
    "trade_id",
    "account",
    "ticker",
    "side",
    "quantity",
    "price",
    "trade_date",
    "settle_date",
    "broker",
    "commission",
    "status",
]

# Fixed-width column specifications for counterparty confirmation files
# Field positions from the legacy spec:
#   Trade ID: 0-16, Account: 16-26, Ticker: 26-36, Side: 36-40,
#   Qty: 40-52 (zero-padded), Price: 52-64 (implied 2 decimals),
#   Currency: 64-67, Date: 67-75 (MMDDYYYY), Status: 75-83
CONFIRM_COLSPECS = [
    (0, 16),   # trade_id
    (16, 26),  # account
    (26, 36),  # ticker
    (36, 40),  # side
    (40, 52),  # quantity (zero-padded integer)
    (52, 64),  # price (implied 2 decimal places)
    (64, 67),  # currency
    (67, 75),  # date (MMDDYYYY)
    (75, 83),  # status
]

CONFIRM_COLUMNS = [
    "trade_id",
    "account",
    "ticker",
    "side",
    "quantity",
    "price",
    "currency",
    "date",
    "status",
]


def load_trades_csv(filepath: Path) -> pd.DataFrame:
    """Load a daily trade CSV file into a DataFrame.

    Args:
        filepath: Path to the CSV file (e.g. daily_trades_20240315.csv).

    Returns:
        DataFrame with typed columns. Dates are parsed as datetime64,
        numeric fields are cast to appropriate types.
    """
    df = pd.read_csv(
        filepath,
        names=TRADE_CSV_COLUMNS,
        header=0,
        dtype={
            "trade_id": str,
            "account": str,
            "ticker": str,
            "side": str,
            "broker": str,
            "status": str,
        },
    )

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["commission"] = pd.to_numeric(df["commission"], errors="coerce").fillna(0.0)

    df["trade_date"] = pd.to_datetime(
        df["trade_date"], format="mixed", dayfirst=False
    ).dt.date

    df["settle_date"] = pd.to_datetime(
        df["settle_date"], format="mixed", dayfirst=False, errors="coerce"
    ).dt.date

    return df


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Load a fixed-width counterparty confirmation file into a DataFrame.

    The file contains HDR (header), TRL (trailer), and trade (T-) records.
    Only trade records are parsed; HDR/TRL lines are skipped.

    Args:
        filepath: Path to the .dat file.

    Returns:
        DataFrame with typed columns. Zero-padded quantities are converted
        to integers, implied-decimal prices are divided by 100, and
        MMDDYYYY dates are parsed.
    """
    trade_lines: list[str] = []
    with open(filepath, "r") as f:
        for line in f:
            if line.startswith("T-"):
                trade_lines.append(line)

    if not trade_lines:
        return pd.DataFrame(columns=CONFIRM_COLUMNS)

    # Write trade lines to a temporary in-memory buffer for read_fwf
    from io import StringIO

    buf = StringIO("".join(trade_lines))

    df = pd.read_fwf(
        buf,
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_COLUMNS,
        dtype=str,
    )

    # Strip whitespace from all string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Convert zero-padded quantity to integer
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")

    # Convert implied-decimal price (divide by 100)
    df["price"] = pd.to_numeric(df["price"], errors="coerce") / 100.0

    # Parse MMDDYYYY date strings
    df["date"] = pd.to_datetime(df["date"], format="%m%d%Y", errors="coerce").dt.date

    return df
