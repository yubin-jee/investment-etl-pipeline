"""Trade validation logic using Pydantic models.

Validates each trade row against the RawTrade model, checks for duplicates,
and flags invalid brokers, quantities, and prices.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from pydantic import ValidationError

from modernized.common.models import RawTrade

logger = logging.getLogger(__name__)

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate a DataFrame of trades using Pydantic model validation.

    Performs:
    - Duplicate detection on trade_id (keeps first occurrence)
    - Pydantic model validation per row (type checks, gt=0 constraints)
    - Broker whitelist check

    Args:
        df: Raw trades DataFrame from parsers.load_trades_csv.

    Returns:
        Tuple of (valid_df, error_df) where error_df includes a
        'validation_error' column describing each failure.
    """
    errors: list[dict[str, Any]] = []
    valid_indices: list[int] = []

    # Step 1: Remove duplicates on trade_id, keeping first occurrence
    pre_dedup_count = len(df)
    df_deduped = df.drop_duplicates(subset="trade_id", keep="first")
    duplicate_count = pre_dedup_count - len(df_deduped)

    if duplicate_count > 0:
        duplicated_mask = df.duplicated(subset="trade_id", keep="first")
        for idx in df[duplicated_mask].index:
            row = df.loc[idx]
            errors.append({
                **row.to_dict(),
                "validation_error": f"Duplicate trade_id: {row['trade_id']}",
            })
        logger.info("Removed %d duplicate trades", duplicate_count)

    # Step 2: Validate each remaining row against Pydantic model
    for idx, row in df_deduped.iterrows():
        row_dict = row.to_dict()

        # Convert pandas Timestamp/NaT to date or None for Pydantic
        for date_col in ["trade_date", "settle_date"]:
            val = row_dict.get(date_col)
            if pd.isna(val):
                row_dict[date_col] = None
            elif hasattr(val, "date"):
                row_dict[date_col] = val.date()

        # Convert pandas NA to None for nullable int
        if pd.isna(row_dict.get("quantity")):
            row_dict["quantity"] = None

        try:
            RawTrade(**row_dict)
        except ValidationError as e:
            errors.append({
                **row.to_dict(),
                "validation_error": str(e),
            })
            logger.warning("Validation failed for trade %s: %s", row.get("trade_id", "?"), e)
            continue

        # Step 3: Broker whitelist check
        if row_dict.get("broker") not in VALID_BROKERS:
            errors.append({
                **row.to_dict(),
                "validation_error": f"Invalid broker: {row_dict.get('broker')}",
            })
            logger.warning("Invalid broker %s for trade %s", row_dict.get("broker"), row_dict.get("trade_id"))
            continue

        valid_indices.append(idx)

    valid_df = df_deduped.loc[valid_indices].copy().reset_index(drop=True)
    error_df = pd.DataFrame(errors) if errors else pd.DataFrame()

    logger.info(
        "Validation complete: %d valid, %d errors (including %d duplicates)",
        len(valid_df),
        len(error_df),
        duplicate_count,
    )

    return valid_df, error_df
