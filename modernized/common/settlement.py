"""Correct T+2 business-day settlement calculation.

The legacy script computed T+2 by naively adding 2 to the day-of-month, which
breaks across weekends and month boundaries. Here we use pandas business-day
offsets so weekends are skipped correctly.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Return the T+2 settlement date, skipping weekends.

    Args:
        trade_date: The trade execution date.

    Returns:
        The settlement date two business days after ``trade_date``.

    Note:
        This skips Saturdays and Sundays but does *not* yet account for market
        holidays. A future enhancement should swap ``BDay`` for a
        ``CustomBusinessDay`` backed by an exchange holiday calendar (e.g.
        ``pandas_market_calendars`` for NYSE) so that settlement dates land on
        actual settlement days.
    """
    settle = pd.Timestamp(trade_date) + pd.tseries.offsets.BDay(2)
    return settle.date()
