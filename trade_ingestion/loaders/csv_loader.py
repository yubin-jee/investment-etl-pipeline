"""Load daily trade CSV files into a pandas DataFrame.

Replaces the manual ``csv.reader`` loop in ``process_trades.py`` lines 27-57.
Uses explicit dtypes so that missing prices surface as ``NaN`` instead of
crashing with a bare ``except``.
"""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import pandas as pd

from trade_ingestion.config import get_path

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
    "trade_date": str,
    "settle_date": str,
    "broker": str,
    "commission": float,
    "status": str,
}


def load_daily_trades(run_date: str) -> pd.DataFrame:
    """Load ``daily_trades_<run_date>.csv`` and return a DataFrame.

    Parameters
    ----------
    run_date : str
        Date string in ``YYYYMMDD`` format used to locate the file.

    Returns
    -------
    pd.DataFrame
    """
    trade_dir = get_path("trade_input")
    pattern = str(Path(trade_dir) / f"daily_trades_{run_date}.csv")
    files = glob.glob(pattern)
    if not files:
        logger.warning("No trade file found matching %s", pattern)
        return pd.DataFrame(columns=CSV_COLUMNS)

    frames: list[pd.DataFrame] = []
    for fp in files:
        logger.info("Loading trades from %s", fp)
        df = pd.read_csv(
            fp,
            names=CSV_COLUMNS,
            dtype=CSV_DTYPES,
            header=0,
            na_values=["", "NA", "N/A"],
        )
        frames.append(df)

    result = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d trade rows", len(result))
    return result
