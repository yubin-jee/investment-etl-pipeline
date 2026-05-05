"""Pandas-based parsers for trade CSV and fixed-width counterparty files.

Replaces the legacy csv.reader and manual fixed-width parsing with
pandas read_csv and read_fwf for robust, typed ingestion.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

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

TRADE_CSV_DTYPES = {
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

CONFIRM_COLSPECS = [
    (0, 14),   # trade_id
    (14, 24),  # account
    (24, 34),  # ticker
    (34, 38),  # side
    (38, 46),  # quantity (zero-padded)
    (46, 56),  # price (implied 2 decimals)
    (56, 59),  # currency
    (59, 67),  # date (MMDDYYYY)
    (67, 76),  # status
]

CONFIRM_COLUMN_NAMES = [
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
    """Load a daily trades CSV file into a DataFrame.

    Args:
        filepath: Path to the CSV file (e.g., daily_trades_20240315.csv).

    Returns:
        DataFrame with typed columns and parsed dates.
    """
    logger.info("Loading trades from %s", filepath)

    df = pd.read_csv(
        filepath,
        names=TRADE_CSV_COLUMNS,
        dtype=TRADE_CSV_DTYPES,
        header=0,
        na_values=[""],
    )

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed")
    df["settle_date"] = pd.to_datetime(df["settle_date"], format="mixed", errors="coerce")

    logger.info("Loaded %d trade rows from %s", len(df), filepath.name)
    return df


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Load a fixed-width counterparty confirmation file.

    Parses the file according to the Meridian fixed-width spec, skipping
    header (HDR) and trailer (TRL) records. Handles zero-padded quantities
    and implied-decimal prices (divide raw integer by 100).

    Args:
        filepath: Path to the .dat confirmation file.

    Returns:
        DataFrame with parsed confirmation records.
    """
    logger.info("Loading counterparty confirms from %s", filepath)

    trade_lines = []
    with open(filepath, "r") as f:
        for line in f:
            if line.startswith("T-"):
                trade_lines.append(line)

    if not trade_lines:
        logger.warning("No trade records found in %s", filepath)
        return pd.DataFrame(columns=CONFIRM_COLUMN_NAMES)

    from io import StringIO

    trade_text = "".join(trade_lines)

    df = pd.read_fwf(
        StringIO(trade_text),
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_COLUMN_NAMES,
        dtype=str,
    )

    df["trade_id"] = df["trade_id"].str.strip()
    df["account"] = df["account"].str.strip()
    df["ticker"] = df["ticker"].str.strip()
    df["side"] = df["side"].str.strip()
    df["status"] = df["status"].str.strip()
    df["currency"] = df["currency"].str.strip()

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    raw_price = pd.to_numeric(df["price"], errors="coerce")
    df["price"] = raw_price / 100.0

    df["date"] = pd.to_datetime(df["date"], format="%m%d%Y", errors="coerce")

    logger.info("Parsed %d counterparty confirms", len(df))
    return df
