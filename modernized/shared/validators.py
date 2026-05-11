"""Validation logic for trades — fixes known issues in the legacy code."""

from __future__ import annotations

import logging
from datetime import date
from typing import List, Tuple

import pandas as pd

from modernized.shared.models import VALID_BROKERS, Trade

logger = logging.getLogger(__name__)


def calculate_t_plus_2(trade_date: date) -> date:
    """Calculate T+2 settlement date using business days.

    Fixes the legacy bug at process_trades.py line 92-102 where:
      - Weekends are ignored
      - Month boundaries are handled with ``day > 30`` heuristic
    """
    td = pd.Timestamp(trade_date)
    settle = td + pd.tseries.offsets.BDay(2)
    return settle.date()


def validate_trades(
    trades: List[Trade],
) -> Tuple[List[Trade], List[dict]]:
    """Validate a list of trades and return (valid_trades, errors).

    Checks performed:
      1. Duplicate trade_id detection (set-based, O(1) lookup)
      2. Broker against VALID_BROKERS whitelist
      3. Quantity > 0  (already enforced by Pydantic, but logged here)
      4. Price > 0     (already enforced by Pydantic, but logged here)
      5. Settlement date — fills in T+2 if missing (correctly)
    """
    valid: List[Trade] = []
    errors: List[dict] = []
    seen_ids: set[str] = set()

    for trade in trades:
        # Duplicate check
        if trade.trade_id in seen_ids:
            errors.append(
                {"trade_id": trade.trade_id, "error": "DUPLICATE", "detail": "Duplicate trade_id"}
            )
            logger.warning("Duplicate trade: %s", trade.trade_id)
            continue
        seen_ids.add(trade.trade_id)

        # Broker validation
        if trade.broker.value not in VALID_BROKERS:
            errors.append(
                {
                    "trade_id": trade.trade_id,
                    "error": "INVALID_BROKER",
                    "detail": f"Broker {trade.broker} not in allowed list",
                }
            )
            logger.warning("Invalid broker %s for trade %s", trade.broker, trade.trade_id)
            continue

        # Quantity check (Pydantic ensures > 0, but explicit for logging)
        if trade.quantity <= 0:
            errors.append(
                {
                    "trade_id": trade.trade_id,
                    "error": "INVALID_QTY",
                    "detail": f"Quantity {trade.quantity} <= 0",
                }
            )
            continue

        # Price check
        if trade.price <= 0:
            errors.append(
                {
                    "trade_id": trade.trade_id,
                    "error": "INVALID_PRICE",
                    "detail": f"Price {trade.price} <= 0",
                }
            )
            continue

        # Fill missing settlement date with proper T+2
        if trade.settle_date is None:
            trade = trade.model_copy(
                update={"settle_date": calculate_t_plus_2(trade.trade_date)}
            )
            logger.info(
                "Calculated T+2 settle date for %s: %s",
                trade.trade_id,
                trade.settle_date,
            )

        valid.append(trade)

    logger.info(
        "Validation complete: %d valid, %d errors (including %d duplicates)",
        len(valid),
        len(errors),
        sum(1 for e in errors if e["error"] == "DUPLICATE"),
    )
    return valid, errors
