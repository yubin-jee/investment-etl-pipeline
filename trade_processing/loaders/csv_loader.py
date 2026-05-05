"""CSV trade file loader using pandas."""

import logging
from pathlib import Path

import pandas as pd

from trade_processing.config import DEFAULT_TRADE_FILE

logger = logging.getLogger(__name__)


def load_trades(file_path: str | Path | None = None) -> pd.DataFrame:
    """Load trades from a CSV file.

    Replicates the field mapping from legacy_scripts/process_trades.py
    but uses pandas for robust parsing and proper dtype handling.
    """
    file_path = Path(file_path) if file_path else DEFAULT_TRADE_FILE
    logger.info("Loading trades from %s", file_path)

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
        parse_dates=["TRADE_DATE", "SETTLE_DATE"],
        date_format="%m/%d/%Y",
    )

    # Rename columns to match internal naming convention
    df = df.rename(columns={
        "TRADE_ID": "trade_id",
        "ACCT_NUM": "account_number",
        "TICKER": "ticker",
        "SIDE": "side",
        "QTY": "quantity",
        "PRICE": "price",
        "TRADE_DATE": "trade_date",
        "SETTLE_DATE": "settle_date",
        "BROKER": "broker",
        "COMMISSION": "commission",
        "STATUS": "status",
    })

    # Convert date columns to date objects (from datetime)
    df["trade_date"] = df["trade_date"].dt.date
    df["settle_date"] = df["settle_date"].apply(
        lambda x: x.date() if pd.notna(x) else None
    )

    logger.info("Loaded %d trades", len(df))
    return df
