"""Dagster assets for the trade processing pipeline.

Each asset corresponds to one stage of the ETL pipeline, using the shared
common layer for parsing, validation, enrichment, and reconciliation.
"""

import pandas as pd
from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
    MetadataValue,
    RetryPolicy,
    asset,
)

from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades
from modernized.option_b_dagster.resources import TradeFileResource

daily_partitions = DailyPartitionsDefinition(start_date="2024-01-01")


_retry = RetryPolicy(max_retries=3, delay=60)


@asset(
    partitions_def=daily_partitions,
    metadata={"description": "Raw trades loaded from the daily CSV file"},
    retry_policy=_retry,
)
def raw_trades(
    context: AssetExecutionContext, trade_files: TradeFileResource
) -> pd.DataFrame:
    """Load raw trade records from the daily CSV for the given partition date."""
    partition_date = context.partition_key
    filepath = trade_files.get_trade_file_path(partition_date)
    context.log.info("Loading trades from %s", filepath)

    df = load_trades_csv(filepath)
    context.add_output_metadata(
        {"row_count": MetadataValue.int(len(df))}
    )
    return df


@asset(metadata={"description": "Validated trades with errors removed"}, retry_policy=_retry)
def validated_trades(
    context: AssetExecutionContext, raw_trades: pd.DataFrame
) -> pd.DataFrame:
    """Validate raw trades and return only the valid records."""
    valid_df, error_df = validate_trades(raw_trades)

    context.log.info(
        "Validation: %d valid, %d errors", len(valid_df), len(error_df)
    )
    context.add_output_metadata(
        {
            "valid_count": MetadataValue.int(len(valid_df)),
            "error_count": MetadataValue.int(len(error_df)),
        }
    )
    return valid_df


@asset(metadata={"description": "Trades enriched with calculated amounts and settlement dates"}, retry_policy=_retry)
def enriched_trades(
    context: AssetExecutionContext, validated_trades: pd.DataFrame
) -> pd.DataFrame:
    """Enrich validated trades with gross/net amounts and settlement dates."""
    df = validated_trades.copy()

    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    df["net_amount"] = df.apply(
        lambda r: round(
            r["gross_amount"] + r["commission"]
            if r["side"] == "BUY"
            else r["gross_amount"] - r["commission"],
            2,
        ),
        axis=1,
    )

    df["settle_date"] = df.apply(
        lambda r: (
            calculate_t_plus_2(r["trade_date"])
            if pd.isna(r["settle_date"]) or r["settle_date"] is None
            else r["settle_date"]
        ),
        axis=1,
    )

    context.log.info("Enriched %d trades", len(df))
    context.add_output_metadata(
        {"row_count": MetadataValue.int(len(df))}
    )
    return df


@asset(metadata={"description": "Counterparty confirmations from fixed-width broker file"}, retry_policy=_retry)
def counterparty_confirms(
    context: AssetExecutionContext, trade_files: TradeFileResource
) -> pd.DataFrame:
    """Load counterparty confirmation records from the fixed-width file."""
    filepath = trade_files.get_confirm_file_path()
    context.log.info("Loading counterparty confirms from %s", filepath)

    df = load_counterparty_file(filepath)
    context.add_output_metadata(
        {"row_count": MetadataValue.int(len(df))}
    )
    return df


@asset(metadata={"description": "Reconciliation results comparing internal trades to confirms"}, retry_policy=_retry)
def reconciled_trades(
    context: AssetExecutionContext,
    enriched_trades: pd.DataFrame,
    counterparty_confirms: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile enriched trades against counterparty confirmations."""
    merged = pd.merge(
        enriched_trades,
        counterparty_confirms,
        on="trade_id",
        how="left",
        suffixes=("", "_cp"),
    )

    def _recon_status(row: pd.Series) -> str:
        if pd.isna(row.get("quantity_cp")):
            return "UNMATCHED"
        if row["quantity"] != row["quantity_cp"]:
            return "QTY_BREAK"
        if abs(row["price"] - row["price_cp"]) > 0.01:
            return "PRICE_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_recon_status, axis=1)

    status_counts = merged["recon_status"].value_counts().to_dict()
    context.log.info("Reconciliation results: %s", status_counts)
    context.add_output_metadata(
        {
            "row_count": MetadataValue.int(len(merged)),
            "matched": MetadataValue.int(status_counts.get("MATCHED", 0)),
            "price_breaks": MetadataValue.int(status_counts.get("PRICE_BREAK", 0)),
            "qty_breaks": MetadataValue.int(status_counts.get("QTY_BREAK", 0)),
            "unmatched": MetadataValue.int(status_counts.get("UNMATCHED", 0)),
        }
    )
    return merged
