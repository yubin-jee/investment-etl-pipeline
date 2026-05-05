"""Trade validation logic using Pydantic models."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from pydantic import ValidationError

from .models import RawTrade

logger = logging.getLogger(__name__)

VALID_BROKERS = {"GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"}


def validate_trades(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate a DataFrame of raw trades.

    Performs duplicate removal, Pydantic model validation on each row,
    and broker-whitelist checking.

    Parameters
    ----------
    df : pd.DataFrame
        Raw trades as returned by :func:`parsers.load_trades_csv`.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        ``(valid_df, error_df)`` where ``error_df`` contains rejected
        rows with an added ``error_reason`` column.
    """
    errors: list[dict] = []
    valid: list[dict] = []

    # --- Duplicate detection (keep first occurrence) ---
    dup_mask = df.duplicated(subset=["trade_id"], keep="first")
    dup_df = df[dup_mask]
    df = df[~dup_mask].copy()

    for _, row in dup_df.iterrows():
        rec = row.to_dict()
        rec["error_reason"] = "DUPLICATE"
        errors.append(rec)

    logger.info("Removed %d duplicate trades", len(dup_df))

    # --- Per-row Pydantic validation + broker whitelist ---
    for _, row in df.iterrows():
        rec = row.to_dict()
        try:
            # Coerce NaN/None price to trigger gt=0 failure.
            if pd.isna(rec.get("price")) or rec.get("price") == "":
                rec["price"] = 0
            if pd.isna(rec.get("quantity")) or rec.get("quantity") == "":
                rec["quantity"] = 0

            trade = RawTrade(
                trade_id=rec["trade_id"],
                account=rec["account"],
                ticker=rec["ticker"],
                side=rec["side"],
                quantity=int(rec["quantity"]),
                price=float(rec["price"]),
                trade_date=rec["trade_date"] if isinstance(rec["trade_date"], date) else rec["trade_date"],
                settle_date=rec.get("settle_date"),
                broker=rec["broker"],
                commission=float(rec["commission"]),
                status=rec["status"],
            )
        except (ValidationError, ValueError, TypeError) as exc:
            rec["error_reason"] = str(exc)
            errors.append(rec)
            logger.debug("Validation failed for %s: %s", rec.get("trade_id"), exc)
            continue

        # Broker whitelist check.
        if trade.broker not in VALID_BROKERS:
            rec["error_reason"] = f"INVALID_BROKER: {trade.broker}"
            errors.append(rec)
            continue

        valid.append(rec)

    valid_df = pd.DataFrame(valid) if valid else pd.DataFrame(columns=df.columns)
    error_df = pd.DataFrame(errors) if errors else pd.DataFrame(columns=[*df.columns, "error_reason"])

    logger.info(
        "Validation complete — %d valid, %d errors",
        len(valid_df),
        len(error_df),
    )
    return valid_df, error_df
