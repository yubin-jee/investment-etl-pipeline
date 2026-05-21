"""Correct T+2 business day settlement date calculation.

Replaces the legacy broken calculation that simply adds 2 calendar days
and uses rough month-end handling.  Uses pandas BDay offset to properly
skip weekends.

NOTE: This implementation skips weekends but does NOT account for market
holidays (e.g. US federal holidays, exchange-specific closures).  For
production use, integrate a holiday calendar via
``pandas.tseries.holiday.USFederalHolidayCalendar`` or a third-party
calendar like ``exchange_calendars``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Compute the T+2 settlement date, skipping weekends.

    Args:
        trade_date: The trade execution date.

    Returns:
        The settlement date two business days after ``trade_date``.

    Examples:
        >>> from datetime import date
        >>> calculate_t_plus_2(date(2024, 3, 15))  # Friday
        datetime.date(2024, 3, 19)                  # Tuesday
        >>> calculate_t_plus_2(date(2024, 3, 14))  # Thursday
        datetime.date(2024, 3, 18)                  # Monday
    """
    ts = pd.Timestamp(trade_date)
    settle_ts = ts + pd.tseries.offsets.BDay(2)
    return settle_ts.date()
