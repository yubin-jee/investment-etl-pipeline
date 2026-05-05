"""Correct T+2 business day settlement date calculation.

Replaces the legacy broken calculation that ignores weekends
by using pandas BDay offset for proper business day arithmetic.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Calculate T+2 settlement date, skipping weekends.

    Uses pandas BDay (Business Day) offset to correctly compute the
    settlement date as 2 business days after the trade date.

    Note: This implementation skips weekends only. For production use,
    integrate a holiday calendar (e.g., NYSE holidays via
    pandas.tseries.holiday.USFederalHolidayCalendar or a custom
    AbstractHolidayCalendar) to also skip market holidays.

    Args:
        trade_date: The trade execution date.

    Returns:
        The T+2 settlement date (2 business days after trade_date).

    Examples:
        >>> calculate_t_plus_2(date(2024, 3, 15))  # Friday
        datetime.date(2024, 3, 19)                  # Tuesday (skips weekend)
        >>> calculate_t_plus_2(date(2024, 3, 14))  # Thursday
        datetime.date(2024, 3, 18)                  # Monday
    """
    ts = pd.Timestamp(trade_date)
    settle_ts = ts + pd.tseries.offsets.BDay(2)
    return settle_ts.date()
