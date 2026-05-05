"""T+2 business day settlement date calculation.

Replaces the legacy broken implementation that simply added 2 calendar
days (ignoring weekends entirely and using naive month-end logic).
"""

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Calculate the T+2 settlement date using business day offsets.

    Uses pandas BDay offset to skip weekends. Returns the settlement
    date that is exactly 2 business days after the trade date.

    Note:
        This implementation handles weekends but does not account for
        market holidays. For production use, integrate a holiday calendar
        (e.g., pandas_market_calendars or a custom holiday list from the
        exchange) to skip holidays as well.

    Args:
        trade_date: The trade execution date.

    Returns:
        The T+2 settlement date (skipping weekends).

    Examples:
        >>> calculate_t_plus_2(date(2024, 3, 15))  # Friday
        datetime.date(2024, 3, 19)  # Tuesday (skips Sat/Sun)
        >>> calculate_t_plus_2(date(2024, 3, 18))  # Monday
        datetime.date(2024, 3, 20)  # Wednesday
    """
    ts = pd.Timestamp(trade_date)
    settle_ts = ts + pd.tseries.offsets.BDay(2)
    return settle_ts.date()
