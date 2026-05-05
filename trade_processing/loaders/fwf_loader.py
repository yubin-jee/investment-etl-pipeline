"""Fixed-width counterparty confirmation file loader using pandas."""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_processing.config import (
    CONFIRM_COLSPECS,
    CONFIRM_COLUMN_NAMES,
    DEFAULT_CONFIRM_FILE,
)

logger = logging.getLogger(__name__)


def _should_skip_line(line: str) -> bool:
    """Return True for header (HDR) and trailer (TRL) rows."""
    stripped = line.strip()
    return stripped.startswith("HDR") or stripped.startswith("TRL")


def load_confirms(file_path: str | Path | None = None) -> pd.DataFrame:
    """Load counterparty confirmations from a fixed-width file.

    Skips header (HDR) and trailer (TRL) rows, parses zero-padded
    quantities, implied-decimal prices, and MMDDYYYY dates.
    """
    file_path = Path(file_path) if file_path else DEFAULT_CONFIRM_FILE
    logger.info("Loading counterparty confirms from %s", file_path)

    # Read lines and filter out HDR/TRL rows
    with open(file_path, "r") as f:
        all_lines = f.readlines()

    data_lines = [line for line in all_lines if not _should_skip_line(line)]

    if not data_lines:
        logger.warning("No data lines found in %s", file_path)
        return pd.DataFrame(columns=CONFIRM_COLUMN_NAMES)

    # Write filtered lines to a temporary string for read_fwf
    from io import StringIO

    filtered_content = "".join(data_lines)

    df = pd.read_fwf(
        StringIO(filtered_content),
        colspecs=CONFIRM_COLSPECS,
        names=CONFIRM_COLUMN_NAMES,
        header=None,
        dtype=str,
    )

    # Strip whitespace from string columns
    for col in df.columns:
        df[col] = df[col].str.strip()

    # Parse quantity (zero-padded integer)
    df["quantity"] = df["quantity"].astype(int)

    # Parse price (implied 2 decimal places)
    df["price"] = df["price"].astype(int) / 100.0

    # Parse trade_date from MMDDYYYY to date
    df["trade_date"] = df["trade_date"].apply(
        lambda x: datetime.strptime(x, "%m%d%Y").date()
    )

    logger.info("Loaded %d counterparty confirms", len(df))
    return df
