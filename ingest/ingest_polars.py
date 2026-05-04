"""Polars-based trade ingestion and validation (lazy evaluation)."""

from __future__ import annotations

import polars as pl

from ingest import CSV_COLUMNS, VALID_BROKERS

# Schema overrides for ``pl.scan_csv`` / ``pl.read_csv``.
_SCHEMA_OVERRIDES: dict[str, pl.DataType] = {
    "trade_id": pl.Utf8,
    "account": pl.Utf8,
    "ticker": pl.Utf8,
    "side": pl.Utf8,
    "quantity": pl.Float64,
    "price": pl.Float64,
    "trade_date": pl.Utf8,
    "settle_date": pl.Utf8,
    "broker": pl.Utf8,
    "commission": pl.Float64,
    "status": pl.Utf8,
}


def load_trades(file_path: str) -> pl.DataFrame:
    """Load trades from a CSV file into a :class:`polars.DataFrame`.

    Uses lazy evaluation internally via :func:`polars.scan_csv` and collects
    at the end.  Date columns are parsed after the initial read.

    Parameters
    ----------
    file_path:
        Path to the daily trades CSV.

    Returns
    -------
    polars.DataFrame
    """
    lf = pl.scan_csv(
        file_path,
        schema_overrides=_SCHEMA_OVERRIDES,
        new_columns=CSV_COLUMNS,
        has_header=True,
    )

    lf = lf.with_columns(
        pl.col("trade_date").str.strptime(pl.Date, "%m/%d/%Y", strict=False),
        pl.col("settle_date").str.strptime(pl.Date, "%m/%d/%Y", strict=False),
    )

    return lf.collect()


def validate_trades(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Validate trades and return accepted and rejected rows.

    Uses lazy evaluation and collects rejected rows separately before
    assembling the final result.

    Parameters
    ----------
    df:
        Raw trade data as returned by :func:`load_trades`.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame]
        ``(clean_df, rejected_df)`` where *rejected_df* contains an extra
        ``rejection_reason`` column.
    """
    lf = df.lazy()
    rejected_parts: list[pl.DataFrame] = []

    # --- Duplicates (keep first) ---
    dup_lf = lf.filter(pl.col("trade_id").is_duplicated())
    # Among duplicated groups, mark all but the first occurrence as rejected.
    dup_marked = (
        dup_lf.with_row_index("_idx")
        .with_columns(
            pl.col("_idx")
            .rank("ordinal")
            .over("trade_id")
            .alias("_rank")
        )
        .filter(pl.col("_rank") > 1)
        .drop("_idx", "_rank")
        .with_columns(pl.lit("duplicate_trade_id").alias("rejection_reason"))
    )
    rejected_parts.append(dup_marked.collect())

    # Keep only unique trade_ids (first occurrence).
    lf = lf.unique(subset=["trade_id"], keep="first")

    # --- Invalid broker ---
    bad_broker = lf.filter(~pl.col("broker").is_in(VALID_BROKERS))
    rejected_parts.append(
        bad_broker.with_columns(pl.lit("invalid_broker").alias("rejection_reason")).collect()
    )
    lf = lf.filter(pl.col("broker").is_in(VALID_BROKERS))

    # --- Non-positive quantity ---
    bad_qty = lf.filter(pl.col("quantity") <= 0)
    rejected_parts.append(
        bad_qty.with_columns(pl.lit("non_positive_quantity").alias("rejection_reason")).collect()
    )
    lf = lf.filter(pl.col("quantity") > 0)

    # --- Missing price (null) — must precede the <= 0 check ---
    nan_price = lf.filter(pl.col("price").is_null())
    rejected_parts.append(
        nan_price.with_columns(pl.lit("missing_price").alias("rejection_reason")).collect()
    )
    lf = lf.filter(pl.col("price").is_not_null())

    # --- Non-positive price ---
    bad_price = lf.filter(pl.col("price") <= 0)
    rejected_parts.append(
        bad_price.with_columns(pl.lit("non_positive_price").alias("rejection_reason")).collect()
    )
    lf = lf.filter(pl.col("price") > 0)

    # Combine rejected rows.
    non_empty = [r for r in rejected_parts if r.height > 0]
    if non_empty:
        rejected_df = pl.concat(non_empty)
    else:
        schema = {**{c: df.schema[c] for c in df.columns}, "rejection_reason": pl.Utf8}
        rejected_df = pl.DataFrame(schema=schema)

    clean_df = lf.collect()
    return clean_df, rejected_df
