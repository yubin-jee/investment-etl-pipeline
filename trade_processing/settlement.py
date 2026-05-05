"""T+2 business day settlement date calculation.

Replaces the broken manual calculation in legacy_scripts/process_trades.py
(lines 94-102) which ignores weekends and has incorrect month-end handling.
"""

import logging
from datetime import date

import pandas as pd
from pandas.tseries.offsets import BDay

logger = logging.getLogger(__name__)


def calculate_settlement_dates(
    trades_df: pd.DataFrame,
    settlement_days: int = 2,
) -> pd.DataFrame:
    """Calculate or fix T+2 settlement dates using business day calendar.

    For trades with missing settle_date, computes trade_date + 2 business days.
    For trades with existing settle_date, recalculates to fix the legacy
    weekend-ignoring bug.
    """
    df = trades_df.copy()

    def _calc_settle(trade_date: date) -> date:
        td = pd.Timestamp(trade_date)
        settle = td + BDay(settlement_days)
        return settle.date()

    df["settle_date"] = df["trade_date"].apply(_calc_settle)

    logger.info("Calculated T+%d settlement dates for %d trades", settlement_days, len(df))
    return df
