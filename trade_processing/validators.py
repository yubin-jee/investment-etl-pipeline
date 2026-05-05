"""Trade validation logic.

Replicates validate_trades() from legacy_scripts/process_trades.py (lines 60-110)
with proper structured logging and DataFrame-based processing.
"""

import logging
from typing import Tuple

import pandas as pd

from trade_processing.config import VALID_BROKERS

logger = logging.getLogger(__name__)


def validate(
    trades_df: pd.DataFrame,
    valid_brokers: list[str] | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trades and return (valid_trades_df, rejected_trades_df).

    Checks:
    - Duplicate detection by trade_id
    - Broker validation against valid broker list
    - Quantity > 0
    - Price > 0
    """
    if valid_brokers is None:
        valid_brokers = VALID_BROKERS

    rejections = []

    # 1. Duplicate detection
    duplicates_mask = trades_df.duplicated(subset=["trade_id"], keep="first")
    dup_df = trades_df[duplicates_mask].copy()
    for _, row in dup_df.iterrows():
        rejections.append({
            "trade_id": row["trade_id"],
            "reason": "DUPLICATE",
            "detail": f"Duplicate trade_id: {row['trade_id']}",
        })
        logger.warning("DUPLICATE: %s", row["trade_id"])
    trades_df = trades_df[~duplicates_mask].copy()

    # 2. Broker validation
    invalid_broker_mask = ~trades_df["broker"].isin(valid_brokers)
    inv_broker_df = trades_df[invalid_broker_mask]
    for _, row in inv_broker_df.iterrows():
        rejections.append({
            "trade_id": row["trade_id"],
            "reason": "INVALID_BROKER",
            "detail": f"Invalid broker: {row['broker']}",
        })
        logger.warning("INVALID BROKER: %s for trade %s", row["broker"], row["trade_id"])
    trades_df = trades_df[~invalid_broker_mask].copy()

    # 3. Quantity > 0
    invalid_qty_mask = trades_df["quantity"] <= 0
    inv_qty_df = trades_df[invalid_qty_mask]
    for _, row in inv_qty_df.iterrows():
        rejections.append({
            "trade_id": row["trade_id"],
            "reason": "INVALID_QUANTITY",
            "detail": f"Quantity <= 0: {row['quantity']}",
        })
        logger.warning("INVALID QTY: %s for trade %s", row["quantity"], row["trade_id"])
    trades_df = trades_df[~invalid_qty_mask].copy()

    # 4. Price > 0
    invalid_price_mask = trades_df["price"] <= 0
    inv_price_df = trades_df[invalid_price_mask]
    for _, row in inv_price_df.iterrows():
        rejections.append({
            "trade_id": row["trade_id"],
            "reason": "INVALID_PRICE",
            "detail": f"Price <= 0: {row['price']}",
        })
        logger.warning("INVALID PRICE: %s for trade %s", row["price"], row["trade_id"])
    trades_df = trades_df[~invalid_price_mask].copy()

    rejected_df = pd.DataFrame(rejections) if rejections else pd.DataFrame(
        columns=["trade_id", "reason", "detail"]
    )

    logger.info(
        "Validation complete: %d valid, %d rejected",
        len(trades_df),
        len(rejected_df),
    )
    return trades_df, rejected_df
