"""Trade validation logic using Pydantic models.

Replaces the legacy ad-hoc validation with structured model-based
checking. Returns both valid and invalid DataFrames so callers can
inspect/log errors.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

import pandas as pd
from pydantic import ValidationError

from modernized.common.models import RawTrade

logger = logging.getLogger(__name__)

VALID_BROKERS = frozenset({"GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"})


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trade rows against the RawTrade Pydantic model.

    Performs:
    1. Duplicate removal on trade_id (keeps first occurrence).
    2. Per-row Pydantic validation (type coercion, constraints).
    3. Broker whitelist check.

    Args:
        df: Raw trades DataFrame from ``parsers.load_trades_csv``.

    Returns:
        Tuple of (valid_df, error_df). ``error_df`` includes an
        ``error_reason`` column describing why each row failed.
    """
    # --- 1. Deduplicate on trade_id ---
    dup_mask = df.duplicated(subset="trade_id", keep="first")
    dup_count = dup_mask.sum()
    if dup_count > 0:
        logger.warning("Removed %d duplicate trade(s)", dup_count)
    df_deduped = df[~dup_mask].copy()

    # --- 2. Per-row validation ---
    valid_indices: list[int] = []
    error_rows: list[dict] = []

    for idx, row in df_deduped.iterrows():
        try:
            # Build kwargs for the Pydantic model
            trade_date_val = row["trade_date"]
            if isinstance(trade_date_val, pd.Timestamp):
                trade_date_val = trade_date_val.date()

            settle_date_val = row["settle_date"]
            if pd.isna(settle_date_val):
                settle_date_val = None
            elif isinstance(settle_date_val, pd.Timestamp):
                settle_date_val = settle_date_val.date()

            # Check for NaN price/quantity before sending to Pydantic
            if pd.isna(row["price"]):
                raise ValueError("price is missing or non-numeric")
            if pd.isna(row["quantity"]):
                raise ValueError("quantity is missing or non-numeric")

            RawTrade(
                trade_id=row["trade_id"],
                account=row["account"],
                ticker=row["ticker"],
                side=row["side"],
                quantity=int(row["quantity"]),
                price=float(row["price"]),
                trade_date=trade_date_val,
                settle_date=settle_date_val,
                broker=row["broker"],
                commission=float(row["commission"]),
                status=row["status"],
            )

            # 3. Broker whitelist
            broker = str(row["broker"]).strip().upper()
            if broker not in VALID_BROKERS:
                error_rows.append(
                    {**row.to_dict(), "error_reason": f"Invalid broker: {broker}"}
                )
                continue

            valid_indices.append(idx)

        except (ValidationError, ValueError, TypeError) as exc:
            error_rows.append({**row.to_dict(), "error_reason": str(exc)})

    valid_df = df_deduped.loc[valid_indices].copy()
    error_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame()

    logger.info(
        "Validation complete: %d valid, %d errors, %d duplicates removed",
        len(valid_df),
        len(error_df),
        dup_count,
    )
    return valid_df, error_df
