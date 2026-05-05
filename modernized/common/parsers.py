"""Pandas-based parsers for trade CSV and fixed-width counterparty files.

Replaces legacy csv.reader and manual fixed-width parsing with
pandas.read_csv and pandas.read_fwf for robust, typed ingestion.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_trades_csv(filepath: Path) -> pd.DataFrame:
    """Load a daily trade CSV into a DataFrame with proper dtypes.

    Args:
        filepath: Path to the daily_trades_*.csv file.

    Returns:
        DataFrame with columns: trade_id, account, ticker, side, quantity,
        price, trade_date, settle_date, broker, commission, status.
    """
    column_names = [
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

    dtypes = {
        "trade_id": str,
        "account": str,
        "ticker": str,
        "side": str,
        "quantity": "Int64",
        "price": float,
        "broker": str,
        "commission": float,
        "status": str,
    }

    df = pd.read_csv(
        filepath,
        names=column_names,
        dtype=dtypes,
        header=0,
        parse_dates=["trade_date", "settle_date"],
        dayfirst=False,
        na_values=["", "NA", "N/A"],
    )

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed")
    df["settle_date"] = pd.to_datetime(df["settle_date"], format="mixed", errors="coerce")

    return df


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Load a fixed-width counterparty confirmation file.

    Parses the fixed-width format, skipping HDR/TRL records, and handles:
    - Zero-padded quantity fields
    - Implied-decimal price (divide raw integer by 100)
    - MMDDYYYY date format

    Args:
        filepath: Path to the counterparty_confirms.dat file.

    Returns:
        DataFrame with columns: trade_id, account, ticker, side, quantity,
        price, currency, date, status.
    """
    # Actual field positions derived from the sample data:
    #   trade_id:  0-14  (14 chars)
    #   account:  14-24  (10 chars, right-padded)
    #   ticker:   24-34  (10 chars, right-padded)
    #   side:     34-38  (4 chars)
    #   quantity: 38-46  (8 chars, zero-padded integer)
    #   price:    46-56  (10 chars, zero-padded, implied 2 decimals)
    #   currency: 56-59  (3 chars)
    #   date:     59-67  (8 chars, MMDDYYYY)
    #   status:   67-76  (up to 9 chars, right-padded)
    records: list[dict] = []
    with open(filepath, "r") as f:
        for line in f:
            if not line.startswith("T-"):
                continue
            raw = line.rstrip("\n")
            records.append({
                "trade_id": raw[0:14].strip(),
                "account": raw[14:24].strip(),
                "ticker": raw[24:34].strip(),
                "side": raw[34:38].strip(),
                "quantity": int(raw[38:46]),
                "price": int(raw[46:56]) / 100.0,
                "currency": raw[56:59].strip(),
                "raw_date": raw[59:67],
                "status": raw[67:].strip(),
            })

    if not records:
        return pd.DataFrame(
            columns=[
                "trade_id", "account", "ticker", "side",
                "quantity", "price", "currency", "date", "status",
            ]
        )

    df = pd.DataFrame(records)

    # Parse MMDDYYYY date
    df["date"] = pd.to_datetime(df["raw_date"], format="%m%d%Y")
    df = df.drop(columns=["raw_date"])

    return df
