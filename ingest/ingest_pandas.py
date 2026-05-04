"""Pandas-based trade ingestion and validation."""

from __future__ import annotations

import pandas as pd

from ingest import CSV_COLUMNS, VALID_BROKERS

# Explicit dtype mapping for ``pd.read_csv``.
_DTYPE_MAP: dict[str, str] = {
    "trade_id": "str",
    "account": "str",
    "ticker": "str",
    "side": "str",
    "quantity": "float64",
    "price": "float64",
    "trade_date": "str",
    "settle_date": "str",
    "broker": "str",
    "commission": "float64",
    "status": "str",
}


def load_trades(file_path: str) -> pd.DataFrame:
    """Load trades from a CSV file into a :class:`pandas.DataFrame`.

    Parameters
    ----------
    file_path:
        Path to the daily trades CSV.

    Returns
    -------
    pandas.DataFrame
        Raw trade data with columns renamed to the canonical schema
        defined in :data:`ingest.CSV_COLUMNS`.
    """
    df = pd.read_csv(
        file_path,
        dtype=_DTYPE_MAP,
        names=CSV_COLUMNS,
        header=0,
    )
    # Parse date columns after loading to avoid mixed-type issues.
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%m/%d/%Y", errors="coerce")
    df["settle_date"] = pd.to_datetime(df["settle_date"], format="%m/%d/%Y", errors="coerce")
    return df


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trades and return accepted and rejected rows.

    Validation rules
    ----------------
    * Duplicate ``trade_id`` values are removed (first occurrence kept).
    * Rows with a ``broker`` not in :data:`ingest.VALID_BROKERS` are rejected.
    * Rows with ``quantity <= 0`` are rejected.
    * Rows with ``price <= 0`` are rejected.

    Parameters
    ----------
    df:
        Raw trade data as returned by :func:`load_trades`.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        ``(clean_df, rejected_df)`` where *rejected_df* contains an extra
        ``rejection_reason`` column describing why each row was rejected.
    """
    rejected_parts: list[pd.DataFrame] = []

    # --- Duplicates ---
    dup_mask = df.duplicated(subset=["trade_id"], keep="first")
    if dup_mask.any():
        dup_rows = df.loc[dup_mask].copy()
        dup_rows["rejection_reason"] = "duplicate_trade_id"
        rejected_parts.append(dup_rows)
    df = df.loc[~dup_mask]

    # --- Invalid broker ---
    bad_broker = ~df["broker"].isin(VALID_BROKERS)
    if bad_broker.any():
        rows = df.loc[bad_broker].copy()
        rows["rejection_reason"] = "invalid_broker"
        rejected_parts.append(rows)
    df = df.loc[~bad_broker]

    # --- Zero / negative quantity ---
    bad_qty = df["quantity"] <= 0
    if bad_qty.any():
        rows = df.loc[bad_qty].copy()
        rows["rejection_reason"] = "non_positive_quantity"
        rejected_parts.append(rows)
    df = df.loc[~bad_qty]

    # --- Zero / negative price ---
    bad_price = df["price"] <= 0
    if bad_price.any():
        rows = df.loc[bad_price].copy()
        rows["rejection_reason"] = "non_positive_price"
        rejected_parts.append(rows)
    df = df.loc[~bad_price]

    # Handle NaN prices (empty values parsed as NaN)
    nan_price = df["price"].isna()
    if nan_price.any():
        rows = df.loc[nan_price].copy()
        rows["rejection_reason"] = "missing_price"
        rejected_parts.append(rows)
    df = df.loc[~nan_price]

    rejected_df = (
        pd.concat(rejected_parts, ignore_index=True) if rejected_parts else pd.DataFrame(columns=[*df.columns, "rejection_reason"])
    )
    clean_df = df.reset_index(drop=True)

    return clean_df, rejected_df
