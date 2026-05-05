"""Pandas-based parsers for trade CSV and fixed-width counterparty files."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
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

CSV_DTYPES = {
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


def load_trades_csv(filepath: Path) -> pd.DataFrame:
    """Load a daily trades CSV file into a DataFrame.

    Parameters
    ----------
    filepath : Path
        Path to the CSV file (e.g. ``daily_trades_20240315.csv``).

    Returns
    -------
    pd.DataFrame
        DataFrame with typed columns ready for validation.
    """
    logger.info("Loading trades from %s", filepath)

    df = pd.read_csv(
        filepath,
        names=CSV_COLUMNS,
        dtype=CSV_DTYPES,
        header=0,
        keep_default_na=False,
    )

    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%m/%d/%Y").dt.date
    df["settle_date"] = pd.to_datetime(
        df["settle_date"], format="%m/%d/%Y", errors="coerce"
    ).apply(lambda x: x.date() if pd.notna(x) else None)

    logger.info("Loaded %d trade rows", len(df))
    return df


# Fixed-width column specifications for counterparty confirmation records.
CONFIRM_COLSPECS = [
    (0, 16),   # trade_id
    (16, 26),  # account
    (26, 36),  # ticker
    (36, 40),  # side
    (40, 52),  # quantity (zero-padded)
    (52, 64),  # price   (implied 2-decimal)
    (64, 67),  # currency
    (67, 75),  # date    (MMDDYYYY)
    (75, 83),  # status
]

CONFIRM_NAMES = [
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


def load_counterparty_file(filepath: Path) -> pd.DataFrame:
    """Parse a fixed-width counterparty confirmation file.

    The file contains HDR (header), TRL (trailer), and trade records.
    Only trade records (lines starting with ``T-``) are extracted.

    Quantity is zero-padded and price uses an implied two-decimal format
    (integer value / 100).

    Parameters
    ----------
    filepath : Path
        Path to the ``.dat`` confirmation file.

    Returns
    -------
    pd.DataFrame
        DataFrame with one row per confirmation record.
    """
    logger.info("Loading counterparty file %s", filepath)

    # Pre-filter: keep only trade record lines (start with "T-").
    trade_lines: list[str] = []
    with open(filepath, "r") as fh:
        for line in fh:
            if line.startswith("T-"):
                trade_lines.append(line)

    if not trade_lines:
        logger.warning("No trade records found in %s", filepath)
        return pd.DataFrame(columns=CONFIRM_NAMES)

    from io import StringIO

    raw_text = "".join(trade_lines)
    df = pd.read_fwf(
        StringIO(raw_text),
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_NAMES,
        dtype=str,
    )

    # Strip whitespace from all string columns.
    for col in df.columns:
        df[col] = df[col].str.strip()

    # Convert zero-padded quantity to int.
    df["quantity"] = df["quantity"].astype(int)

    # Implied two-decimal price: divide raw integer by 100.
    df["price"] = df["price"].astype(int) / 100.0

    # Parse MMDDYYYY dates.
    df["date"] = df["date"].apply(
        lambda s: datetime.strptime(s, "%m%d%Y").date()
    )

    logger.info("Parsed %d counterparty confirms", len(df))
    return df
