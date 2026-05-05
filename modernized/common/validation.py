"""Trade validation logic using Pydantic model validation.

Validates each trade row against the RawTrade model and applies
business rules (broker whitelist, deduplication).
"""

import logging
from typing import Optional

import pandas as pd
from pydantic import ValidationError

from modernized.common.models import RawTrade

logger = logging.getLogger(__name__)

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


def validate_trades(
    df: pd.DataFrame,
    valid_brokers: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trade rows against the Pydantic model and business rules.

    Checks for:
    - Duplicate trade_id values (keeps first occurrence)
    - Pydantic model validation (types, gt=0 constraints, date parsing)
    - Broker whitelist membership

    Args:
        df: Raw trades DataFrame from load_trades_csv.
        valid_brokers: Allowed broker codes. Defaults to the standard list.

    Returns:
        Tuple of (valid_trades_df, error_trades_df). The error DataFrame
        includes an 'error_reason' column describing the validation failure.
    """
    if valid_brokers is None:
        valid_brokers = VALID_BROKERS

    initial_count = len(df)

    # --- Deduplication ---
    dup_mask = df.duplicated(subset=["trade_id"], keep="first")
    dup_count = dup_mask.sum()
    if dup_count > 0:
        logger.warning("Removed %d duplicate trade(s)", dup_count)
    df_deduped = df[~dup_mask].copy()

    valid_rows = []
    error_rows = []

    for idx, row in df_deduped.iterrows():
        row_dict = row.to_dict()

        # Convert pandas Timestamps to date-formatted strings for Pydantic
        for date_col in ("trade_date", "settle_date"):
            val = row_dict.get(date_col)
            if pd.isna(val) or val is None:
                row_dict[date_col] = None
            elif hasattr(val, "strftime"):
                row_dict[date_col] = val.date() if hasattr(val, "date") else val

        # Convert pandas NA to None for quantity/price
        for num_col in ("quantity", "price", "commission"):
            val = row_dict.get(num_col)
            if pd.isna(val):
                row_dict[num_col] = None

        try:
            trade = RawTrade(**row_dict)
        except ValidationError as e:
            error_dict = row.to_dict()
            error_dict["error_reason"] = str(e)
            error_rows.append(error_dict)
            continue

        # Broker whitelist check
        if row_dict["broker"] not in valid_brokers:
            error_dict = row.to_dict()
            error_dict["error_reason"] = f"Invalid broker: {row_dict['broker']}"
            error_rows.append(error_dict)
            continue

        valid_rows.append(row_dict)

    valid_df = pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=df.columns)
    error_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame()

    logger.info(
        "Validation complete: %d loaded, %d duplicates, %d errors, %d valid",
        initial_count,
        dup_count,
        len(error_rows),
        len(valid_rows),
    )

    return valid_df, error_df
