"""Row-level validation using pydantic models.

Replaces the manual ``if`` checks in ``validate_trades()`` (legacy
``process_trades.py`` lines 60-110).  Validation errors are collected into a
structured list instead of being ``print()``-ed.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from pydantic import ValidationError

from trade_ingestion.models import Trade

logger = logging.getLogger(__name__)


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Validate each row by constructing a :class:`Trade` model.

    Returns
    -------
    tuple[pd.DataFrame, list[dict]]
        ``(valid_df, errors_list)`` where each error dict has keys
        ``trade_id``, ``row_index``, and ``details``.
    """
    valid_indices: list[int] = []
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for idx, row in df.iterrows():
        trade_id = str(row.get("trade_id", f"row-{idx}"))

        if trade_id in seen_ids:
            errors.append(
                {
                    "trade_id": trade_id,
                    "row_index": idx,
                    "details": "Duplicate trade_id",
                }
            )
            logger.warning("Duplicate trade_id: %s", trade_id)
            continue

        try:
            Trade(
                trade_id=row.get("trade_id"),
                account=row.get("account"),
                ticker=row.get("ticker"),
                side=row.get("side"),
                quantity=row.get("quantity"),
                price=row.get("price"),
                trade_date=row.get("trade_date"),
                settle_date=row.get("settle_date"),
                broker=row.get("broker"),
                commission=row.get("commission"),
                status=row.get("status"),
            )
        except (ValidationError, Exception) as exc:
            errors.append(
                {
                    "trade_id": trade_id,
                    "row_index": idx,
                    "details": str(exc),
                }
            )
            logger.warning("Validation failed for %s: %s", trade_id, exc)
            continue

        seen_ids.add(trade_id)
        valid_indices.append(idx)  # type: ignore[arg-type]

    valid_df = df.loc[valid_indices].copy()
    logger.info(
        "Validation complete — %d valid, %d errors", len(valid_df), len(errors)
    )
    return valid_df, errors
