"""Trade amount calculations.

Replicates calc_trade_amounts() from legacy_scripts/process_trades.py (lines 113-126).
"""

import logging
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_amounts(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate gross_amount, net_amount for each trade.

    gross_amount = quantity * price
    For BUY: net_amount = gross_amount + commission
    For SELL: net_amount = gross_amount - commission
    """
    df = trades_df.copy()

    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    df["net_amount"] = df.apply(
        lambda row: round(
            row["gross_amount"] - row["commission"]
            if row["side"] == "SELL"
            else row["gross_amount"] + row["commission"],
            2,
        ),
        axis=1,
    )

    logger.info("Calculated amounts for %d trades", len(df))
    return df
