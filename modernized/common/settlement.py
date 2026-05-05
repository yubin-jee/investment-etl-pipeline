"""T+2 business-day settlement date calculation.

Replaces the legacy broken settlement logic that simply added 2 calendar
days (ignoring weekends and holidays) with a correct business-day offset.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Compute the T+2 settlement date, skipping weekends.

    Uses ``pd.tseries.offsets.BDay`` (Business Day) to add exactly 2
    business days to the trade date. Weekends (Saturday/Sunday) are
    automatically skipped.

    Note:
        This implementation does **not** account for market holidays
        (e.g. US federal holidays, exchange-specific closures). For
        production use, integrate a holiday calendar such as
        ``pandas.tseries.holiday.USFederalHolidayCalendar`` or the
        ``exchange_calendars`` package.

    Args:
        trade_date: The execution date of the trade.

    Returns:
        The T+2 settlement date (a business day).

    Examples:
        >>> from datetime import date
        >>> calculate_t_plus_2(date(2024, 3, 15))  # Friday
        datetime.date(2024, 3, 19)  # Tuesday (skips weekend)
        >>> calculate_t_plus_2(date(2024, 3, 18))  # Monday
        datetime.date(2024, 3, 20)  # Wednesday
    """
    settlement_ts = pd.Timestamp(trade_date) + pd.tseries.offsets.BDay(2)
    return settlement_ts.date()
