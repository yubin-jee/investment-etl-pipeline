"""Trade enrichment transforms — vectorized pandas operations.

Replaces the per-row ``calc_trade_amounts()`` loop in ``process_trades.py``
(lines 113-126) and the broken manual T+2 settlement logic (lines 92-102).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``gross_amount`` and ``net_amount`` columns (vectorized).

    * BUY:  net = gross + commission
    * SELL: net = gross − commission
    """
    out = df.copy()
    out["gross_amount"] = (out["quantity"] * out["price"]).round(2)
    out["net_amount"] = np.where(
        out["side"] == "SELL",
        (out["gross_amount"] - out["commission"]).round(2),
        (out["gross_amount"] + out["commission"]).round(2),
    )
    logger.info("Calculated gross/net amounts for %d trades", len(out))
    return out


def _business_day_offset(start: date, days: int) -> date:
    """Advance *start* by *days* business days (Mon-Fri only).

    Uses ``pandas_market_calendars`` for US equity market holidays when
    available; falls back to simple weekday-skip logic.
    """
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.valid_days(
            start_date=start.isoformat(),
            end_date=(start + timedelta(days=days * 3 + 10)).isoformat(),
        )
        future_days = [d.date() for d in schedule if d.date() > start]
        if len(future_days) >= days:
            return future_days[days - 1]
    except Exception:
        logger.debug("pandas_market_calendars unavailable; using weekday fallback")

    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def fill_settlement_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing ``settle_date`` with T+2 business days from ``trade_date``.

    Replaces the legacy ``day + 2`` / ``if day > 30`` hack.
    """
    out = df.copy()

    out["trade_date"] = pd.to_datetime(
        out["trade_date"], format="mixed", dayfirst=False
    ).dt.date

    out["settle_date"] = out["settle_date"].astype(object)

    mask = out["settle_date"].isna() | (out["settle_date"].astype(str).str.strip() == "")

    for idx in out.index[mask]:
        td = out.at[idx, "trade_date"]
        if isinstance(td, date):
            out.at[idx, "settle_date"] = _business_day_offset(td, 2)

    for idx2 in out.index[~mask]:
        val = out.at[idx2, "settle_date"]
        if isinstance(val, date):
            continue
        if isinstance(val, str) and val.strip():
            out.at[idx2, "settle_date"] = pd.to_datetime(
                val, format="mixed", dayfirst=False
            ).date()

    logger.info("Settlement dates filled for %d rows", mask.sum())
    return out
