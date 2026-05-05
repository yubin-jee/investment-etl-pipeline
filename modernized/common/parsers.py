"""Pandas-based parsers for trade CSV and fixed-width counterparty files.

Replaces the legacy csv.reader and manual fixed-width parsing with
pandas read_csv / read_fwf for robust, typed ingestion.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

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

# Fixed-width column specifications for counterparty confirmation records.
# The legacy spec listed wider positions (0-16, 16-26, …, 75-83) but the
# actual data files in the repository use 76-character lines.  The correct
# field boundaries (verified against the sample .dat files) are below.
CONFIRM_COLSPECS = [
    (0, 14),   # trade_id
    (14, 22),  # account
    (22, 34),  # ticker
    (34, 38),  # side
    (38, 46),  # quantity (zero-padded integer)
    (46, 56),  # price (implied 2 decimal places)
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
    """Load a daily trade CSV file into a DataFrame.

    Args:
        filepath: Path to the CSV file (e.g. daily_trades_20240315.csv).

    Returns:
        DataFrame with typed columns. Dates are parsed as datetime64,
        numeric columns are coerced (invalid values become NaN).
    """
    logger.info("Loading trade CSV: %s", filepath)

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

    # Parse dates — trade_date is always present, settle_date may be empty
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed", dayfirst=False)
    df["settle_date"] = pd.to_datetime(
        df["settle_date"], format="mixed", dayfirst=False, errors="coerce"
    )

    # Coerce numeric columns (handles missing/malformed values)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["commission"] = pd.to_numeric(df["commission"], errors="coerce").fillna(0.0)

    logger.info("Loaded %d trade rows from %s", len(df), filepath)
    return df


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Load a fixed-width counterparty confirmation file.

    Skips HDR (header) and TRL (trailer) records, parsing only trade
    confirmation lines (those starting with 'T-').

    The quantity field is zero-padded and the price field uses implied
    2-decimal precision (divide raw integer by 100). The date field is
    in MMDDYYYY format.

    Args:
        filepath: Path to the .dat file.

    Returns:
        DataFrame with parsed confirmation records.
    """
    logger.info("Loading counterparty file: %s", filepath)

    # Read the raw lines, filtering out header/trailer records
    trade_lines: list[str] = []
    with open(filepath, "r") as fh:
        for line in fh:
            if line.startswith("T-"):
                trade_lines.append(line)

    if not trade_lines:
        logger.warning("No trade records found in %s", filepath)
        return pd.DataFrame(columns=CONFIRM_COLUMN_NAMES)

    # Write filtered lines to a temporary in-memory buffer for read_fwf
    from io import StringIO

    buffer = StringIO("\n".join(trade_lines))

    df = pd.read_fwf(
        buffer,
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_COLUMN_NAMES,
        header=None,
    )

    # Strip whitespace from string columns
    for col in ["trade_id", "account", "ticker", "side", "currency", "status"]:
        df[col] = df[col].astype(str).str.strip()

    # Quantity is zero-padded integer
    df["quantity"] = df["quantity"].astype(int)

    # Price has implied 2 decimal places
    df["price"] = df["price"].astype(float) / 100.0

    # Parse MMDDYYYY date
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%m%d%Y")

    logger.info("Parsed %d counterparty confirms from %s", len(df), filepath)
    return df
