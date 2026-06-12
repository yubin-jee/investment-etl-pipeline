"""Pandas-based parsers for trade CSVs and counterparty confirmation files.

These replace the legacy ``csv.reader`` positional indexing and the hand-rolled
fixed-width string slicing in ``legacy_scripts/process_trades.py``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Column names for the daily trade CSV files. The legacy header row is noisy
# (it wraps awkwardly), so we declare the schema explicitly and skip the header.
TRADE_COLUMNS = [
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

# Fixed-width field positions for the counterparty confirmation ``.dat`` file.
# Matches the spec recovered from the legacy script's docstring.
CONFIRM_COLSPECS = [
    (0, 16),   # trade_id
    (16, 26),  # account
    (26, 36),  # ticker
    (36, 40),  # side
    (40, 52),  # quantity (zero padded)
    (52, 64),  # price (implied 2 decimals)
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
    """Load a daily trade CSV into a typed DataFrame.

    Args:
        filepath: Path to a ``daily_trades_*.csv`` file.

    Returns:
        A DataFrame with the columns in :data:`TRADE_COLUMNS`. ``trade_date``
        and ``settle_date`` are parsed to ``datetime64`` (empty settle dates
        become ``NaT``); ``quantity``/``price``/``commission`` are numeric.
    """
    filepath = Path(filepath)
    df = pd.read_csv(
        filepath,
        header=0,
        names=TRADE_COLUMNS,
        dtype={
            "trade_id": "string",
            "account": "string",
            "ticker": "string",
            "side": "string",
            "broker": "string",
            "status": "string",
        },
        skipinitialspace=True,
    )

    # Strip stray whitespace/newlines that the legacy files sometimes contain.
    for col in ["trade_id", "account", "ticker", "side", "broker", "status"]:
        df[col] = df[col].str.strip()

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["commission"] = pd.to_numeric(df["commission"], errors="coerce")
    df["trade_date"] = pd.to_datetime(
        df["trade_date"], format="%m/%d/%Y", errors="coerce"
    )
    df["settle_date"] = pd.to_datetime(
        df["settle_date"], format="%m/%d/%Y", errors="coerce"
    )
    return df


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Parse the fixed-width counterparty confirmation ``.dat`` file.

    Only ``T-`` trade records are returned; ``HDR`` and ``TRL`` header/trailer
    records are skipped. The implied-decimal price (last two digits are cents)
    is divided by 100, and the ``MMDDYYYY`` date column is parsed to a datetime.

    Args:
        filepath: Path to the ``counterparty_confirms.dat`` file.

    Returns:
        A DataFrame with the columns in :data:`CONFIRM_COLUMNS`.
    """
    filepath = Path(filepath)
    df = pd.read_fwf(
        filepath,
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_COLUMNS,
        dtype="string",
    )

    # Keep only trade records (drop HDR / TRL lines).
    df = df[df["trade_id"].str.startswith("T-", na=False)].copy()

    for col in ["trade_id", "account", "ticker", "side", "currency", "status"]:
        df[col] = df[col].str.strip()

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    # Price carries two implied decimal places.
    df["price"] = pd.to_numeric(df["price"], errors="coerce") / 100.0
    df["date"] = pd.to_datetime(df["date"], format="%m%d%Y", errors="coerce")

    return df.reset_index(drop=True)
