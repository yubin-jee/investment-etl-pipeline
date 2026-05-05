"""Correct T+2 business-day settlement date calculation."""

from __future__ import annotations

from datetime import date

import pandas as pd


def calculate_t_plus_2(trade_date: date) -> date:
    """Compute the T+2 settlement date, skipping weekends.

    Uses :class:`pandas.tseries.offsets.BDay` so that Saturdays and
    Sundays are excluded automatically.

    .. note::
       Market holidays are *not* handled here.  For production use,
       integrate a holiday calendar (e.g. ``pandas_market_calendars``
       or a custom ``AbstractHolidayCalendar``) and pass it via
       ``CustomBusinessDay(holidays=...)``.

    Parameters
    ----------
    trade_date : date
        The trade execution date.

    Returns
    -------
    date
        The settlement date (T+2 business days after *trade_date*).
    """
    ts = pd.Timestamp(trade_date)
    settle_ts = ts + pd.tseries.offsets.BDay(2)
    return settle_ts.date()
