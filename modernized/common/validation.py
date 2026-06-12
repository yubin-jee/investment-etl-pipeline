"""Shared trade validation logic.

Validates a raw trades DataFrame (as produced by
:func:`modernized.common.parsers.load_trades_csv`) against the
:class:`modernized.common.models.RawTrade` Pydantic model plus the broker
whitelist, and splits it into valid and error rows.
"""

from __future__ import annotations

import pandas as pd
from pydantic import ValidationError

from modernized.common.models import RawTrade

# Broker whitelist carried over from the legacy script.
VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trades, returning ``(valid_df, error_df)``.

    Validation rules:

    * Duplicate ``trade_id`` values are dropped (first occurrence kept). The
      dropped rows are tagged with ``error_reason == "DUPLICATE"``.
    * Each remaining row is validated against the :class:`RawTrade` model
      (enforces ``side in {BUY, SELL}``, ``quantity > 0``, ``price > 0``,
      valid dates, etc.).
    * Broker must be in :data:`VALID_BROKERS`.

    Args:
        df: Raw trades DataFrame from the parser.

    Returns:
        A tuple ``(valid_df, error_df)``. ``valid_df`` has the same columns as
        the input. ``error_df`` adds an ``error_reason`` column describing why
        each row failed.
    """
    error_rows: list[dict] = []

    # 1. Duplicate detection on trade_id.
    dup_mask = df.duplicated(subset="trade_id", keep="first")
    for _, row in df[dup_mask].iterrows():
        record = row.to_dict()
        record["error_reason"] = "DUPLICATE"
        error_rows.append(record)

    deduped = df[~dup_mask]

    valid_indices: list[int] = []
    for idx, row in deduped.iterrows():
        record = row.to_dict()

        # Broker whitelist check (kept explicit for a clear error reason).
        if record.get("broker") not in VALID_BROKERS:
            record["error_reason"] = f"INVALID_BROKER:{record.get('broker')}"
            error_rows.append(record)
            continue

        try:
            RawTrade(
                trade_id=record["trade_id"],
                account=record["account"],
                ticker=record["ticker"],
                side=record["side"],
                quantity=_as_int(record["quantity"]),
                price=_as_float(record["price"]),
                trade_date=_as_date(record["trade_date"]),
                settle_date=_as_date(record["settle_date"]),
                broker=record["broker"],
                commission=_as_float(record["commission"]),
                status=record["status"],
            )
        except (ValidationError, ValueError, TypeError) as exc:
            record["error_reason"] = f"VALIDATION:{_first_error(exc)}"
            error_rows.append(record)
            continue

        valid_indices.append(idx)

    valid_df = deduped.loc[valid_indices].reset_index(drop=True)
    error_df = pd.DataFrame(error_rows)
    return valid_df, error_df


def _as_int(value: object) -> object:
    """Coerce to int, leaving NaN/None alone so the model raises a clear error."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    return int(value)


def _as_float(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    return float(value)


def _as_date(value: object) -> object:
    """Convert a pandas Timestamp/NaT to a ``date`` or ``None``."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _first_error(exc: Exception) -> str:
    """Return a short description of the first validation error."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        return f"{loc}:{first.get('type', 'invalid')}"
    return str(exc)
