"""Dagster asset definitions for trade processing.

Each asset represents a discrete step in the pipeline, enabling
Dagster's built-in lineage tracking, retry policies, and UI
observability.

Asset graph:
    raw_trades ──► validated_trades ──► enriched_trades ──┐
                                                          ├──► reconciled_trades
    counterparty_confirms ────────────────────────────────┘
"""

from __future__ import annotations

from datetime import datetime

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

retry_policy = RetryPolicy(max_retries=3, delay=60)


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    group_name="trade_processing",
)
def raw_trades(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
) -> pd.DataFrame:
    """Load raw trade CSV for the given partition date.

    Reads the daily trade file using pandas-based parsing with
    explicit column names and dtype enforcement.
    """
    run_date = context.partition_key.replace("-", "")
    trade_path = trade_files.trade_file_path(run_date)
    context.log.info("Loading trades from %s", trade_path)

    df = load_trades_csv(trade_path)

    context.add_output_metadata({
        "row_count": MetadataValue.int(len(df)),
        "columns": MetadataValue.text(", ".join(df.columns.tolist())),
        "file_path": MetadataValue.path(str(trade_path)),
    })

    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    group_name="trade_processing",
)
def validated_trades(
    context: AssetExecutionContext,
    raw_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Validate trades using Pydantic models and business rules.

    Removes duplicates, validates each row against the RawTrade model,
    and checks broker whitelist membership.
    """
    valid_df, error_df = validate_trades(raw_trades)

    error_count = len(error_df)
    context.log.info(
        "Validation: %d valid, %d errors", len(valid_df), error_count,
    )

    context.add_output_metadata({
        "valid_count": MetadataValue.int(len(valid_df)),
        "error_count": MetadataValue.int(error_count),
        "error_rate": MetadataValue.float(
            error_count / max(len(raw_trades), 1) * 100,
        ),
    })

    return valid_df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    group_name="trade_processing",
)
def enriched_trades(
    context: AssetExecutionContext,
    validated_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Enrich trades with calculated amounts and corrected settlement dates.

    - Calculates gross_amount = quantity * price
    - Calculates net_amount (adjusted for BUY/SELL commission)
    - Fixes missing settlement dates using T+2 business day logic
    """
    df = validated_trades.copy()

    # Fix settlement dates
    missing_settle = df["settle_date"].isna()
    if missing_settle.any():
        context.log.info("Fixing %d missing settlement dates", missing_settle.sum())
        df.loc[missing_settle, "settle_date"] = df.loc[missing_settle, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )

    # Calculate amounts
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)

    context.add_output_metadata({
        "row_count": MetadataValue.int(len(df)),
        "total_gross": MetadataValue.float(float(df["gross_amount"].sum())),
        "total_net": MetadataValue.float(float(df["net_amount"].sum())),
        "settlement_dates_fixed": MetadataValue.int(int(missing_settle.sum())),
    })

    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    group_name="trade_processing",
)
def counterparty_confirms(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
) -> pd.DataFrame:
    """Load counterparty confirmation file.

    Parses the fixed-width .dat file, handling zero-padded quantities,
    implied-decimal prices, and MMDDYYYY date format.
    """
    confirm_path = trade_files.confirm_file_path()
    context.log.info("Loading counterparty confirms from %s", confirm_path)

    df = load_counterparty_file(confirm_path)

    context.add_output_metadata({
        "row_count": MetadataValue.int(len(df)),
        "file_path": MetadataValue.path(str(confirm_path)),
    })

    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    group_name="trade_processing",
)
def reconciled_trades(
    context: AssetExecutionContext,
    enriched_trades: pd.DataFrame,
    counterparty_confirms: pd.DataFrame,
    trade_files: TradeFileResource,
) -> pd.DataFrame:
    """Reconcile enriched trades against counterparty confirmations.

    Performs an O(n) hash join on trade_id and detects price/quantity
    breaks with configurable tolerance.
    """
    tolerance = 0.01

    if counterparty_confirms.empty:
        enriched_trades = enriched_trades.copy()
        enriched_trades["recon_status"] = "UNMATCHED"
        return enriched_trades

    merged = pd.merge(
        enriched_trades,
        counterparty_confirms[["trade_id", "price", "quantity"]],
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )

    def _status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(row["price"] - row["price_confirm"]) > tolerance:
            return "PRICE_BREAK"
        if row["quantity"] != row.get("quantity_confirm"):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_status, axis=1)
    merged = merged.drop(columns=["price_confirm", "quantity_confirm"], errors="ignore")

    # Add processed timestamp and write output
    run_date = context.partition_key.replace("-", "")
    merged["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    output_dir = trade_files.output_dir()
    output_path = output_dir / f"processed_trades_{run_date}.csv"
    merged.to_csv(output_path, index=False)

    recon_counts = merged["recon_status"].value_counts()
    matched = int(recon_counts.get("MATCHED", 0))
    breaks = int(recon_counts.get("PRICE_BREAK", 0) + recon_counts.get("QTY_BREAK", 0))
    unmatched = int(recon_counts.get("UNMATCHED", 0))

    context.log.info("Reconciliation: %d matched, %d breaks, %d unmatched", matched, breaks, unmatched)

    context.add_output_metadata({
        "matched": MetadataValue.int(matched),
        "breaks": MetadataValue.int(breaks),
        "unmatched": MetadataValue.int(unmatched),
        "output_path": MetadataValue.path(str(output_path)),
    })

    return merged
