"""Trade validation logic using Pydantic models.

Replaces the legacy ad-hoc validation with structured model-based
validation, deduplication, and broker whitelist checking.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd
from pydantic import ValidationError

from modernized.common.models import RawTrade

logger = logging.getLogger(__name__)

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


def _validate_row(row: pd.Series) -> Optional[str]:
    """Validate a single trade row against the Pydantic model.

    Returns:
        None if valid, or an error message string if invalid.
    """
    try:
        settle = row.get("settle_date")
        if pd.isna(settle):
            settle = None

        RawTrade(
            trade_id=row["trade_id"],
            account=row["account"],
            ticker=row["ticker"],
            side=row["side"],
            quantity=int(row["quantity"]) if pd.notna(row["quantity"]) else 0,
            price=float(row["price"]) if pd.notna(row["price"]) else 0.0,
            trade_date=row["trade_date"] if isinstance(row["trade_date"], date) else None,
            settle_date=settle if isinstance(settle, date) else None,
            broker=row["broker"],
            commission=float(row["commission"]) if pd.notna(row["commission"]) else 0.0,
            status=row["status"],
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return str(exc)

    broker = str(row["broker"]).strip().upper()
    if broker not in VALID_BROKERS:
        return f"Invalid broker: {broker}"

    return None


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate a DataFrame of raw trades.

    Performs:
      1. Deduplication on trade_id (keeps first occurrence).
      2. Per-row Pydantic model validation (type checks, gt=0, etc.).
      3. Broker whitelist checking.

    Args:
        df: Raw trades DataFrame from ``load_trades_csv``.

    Returns:
        A tuple of (valid_df, error_df). ``error_df`` includes a
        ``validation_error`` column describing what failed.
    """
    if df.empty:
        return df.copy(), pd.DataFrame(columns=[*df.columns, "validation_error"])

    # --- Deduplication ---
    dup_mask = df.duplicated(subset=["trade_id"], keep="first")
    duplicates = df[dup_mask].copy()
    if not duplicates.empty:
        duplicates["validation_error"] = "Duplicate trade_id"
        logger.info("Removed %d duplicate trades", len(duplicates))

    df_deduped = df[~dup_mask].copy()

    # --- Row-level validation ---
    errors: list[str | None] = []
    for _, row in df_deduped.iterrows():
        errors.append(_validate_row(row))

    df_deduped["validation_error"] = errors
    valid_mask = df_deduped["validation_error"].isna()

    valid_df = df_deduped[valid_mask].drop(columns=["validation_error"]).reset_index(drop=True)
    invalid_df = df_deduped[~valid_mask].reset_index(drop=True)

    # Combine invalid rows with duplicates
    error_df = pd.concat([duplicates, invalid_df], ignore_index=True)

    logger.info(
        "Validation complete: %d valid, %d errors (incl. %d duplicates)",
        len(valid_df),
        len(error_df),
        len(duplicates),
    )

    return valid_df, error_df
