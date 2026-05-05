"""Dagster software-defined assets for the trade processing pipeline."""

import pandas as pd
from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
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
    metadata={"description": "Raw trades loaded from the daily CSV file"},
)
def raw_trades(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
) -> pd.DataFrame:
    """Load raw trades from the daily CSV for the partitioned run date."""
    run_date = context.partition_key
    file_path = trade_files.get_trade_file_path(run_date)
    context.log.info("Loading trades from %s", file_path)

    df = load_trades_csv(file_path)
    context.log.info("Loaded %d raw trade rows", len(df))

    context.add_output_metadata({"row_count": len(df)})
    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    metadata={"description": "Trades validated against Pydantic models and business rules"},
)
def validated_trades(
    context: AssetExecutionContext,
    raw_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Validate raw trades and separate valid from erroneous records."""
    valid_df, error_df = validate_trades(raw_trades)
    valid_count = len(valid_df)
    error_count = len(error_df)

    context.log.info("Validation: %d valid, %d errors", valid_count, error_count)

    context.add_output_metadata({
        "valid_count": valid_count,
        "error_count": error_count,
    })
    return valid_df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    metadata={"description": "Trades enriched with calculated amounts and settlement dates"},
)
def enriched_trades(
    context: AssetExecutionContext,
    validated_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Enrich validated trades with gross/net amounts and settlement dates."""
    df = validated_trades.copy()

    df["gross_amount"] = df["quantity"] * df["price"]

    df["net_amount"] = df.apply(
        lambda row: (
            row["gross_amount"] + row["commission"]
            if row["side"] == "BUY"
            else row["gross_amount"] - row["commission"]
        ),
        axis=1,
    )

    df["gross_amount"] = df["gross_amount"].round(2)
    df["net_amount"] = df["net_amount"].round(2)

    missing_settle = df["settle_date"].isna()
    if missing_settle.any():
        context.log.info(
            "Fixing %d missing settlement dates via T+2 calculation",
            missing_settle.sum(),
        )
        df.loc[missing_settle, "settle_date"] = df.loc[missing_settle, "trade_date"].apply(
            lambda td: calculate_t_plus_2(td.date() if hasattr(td, "date") else td)
        )

    context.log.info("Enriched %d trades", len(df))
    context.add_output_metadata({"row_count": len(df)})
    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    metadata={"description": "Counterparty confirmation records from fixed-width file"},
)
def counterparty_confirms(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
) -> pd.DataFrame:
    """Load counterparty confirmation records from the fixed-width file."""
    file_path = trade_files.get_confirm_file_path()
    context.log.info("Loading counterparty confirms from %s", file_path)

    df = load_counterparty_file(file_path)
    context.log.info("Loaded %d counterparty confirms", len(df))

    context.add_output_metadata({"row_count": len(df)})
    return df


@asset(
    partitions_def=daily_partitions,
    retry_policy=retry_policy,
    metadata={"description": "Reconciled trades merged with counterparty confirms"},
)
def reconciled_trades(
    context: AssetExecutionContext,
    enriched_trades: pd.DataFrame,
    counterparty_confirms: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile enriched trades against counterparty confirmations."""
    df = pd.merge(
        enriched_trades,
        counterparty_confirms,
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )

    def _recon_status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(row["price"] - row["price_confirm"]) > 0.01:
            return "PRICE_BREAK"
        if row["quantity"] != row.get("quantity_confirm"):
            return "QTY_BREAK"
        return "MATCHED"

    df["recon_status"] = df.apply(_recon_status, axis=1)

    matched = (df["recon_status"] == "MATCHED").sum()
    breaks = df["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
    unmatched = (df["recon_status"] == "UNMATCHED").sum()

    context.log.info(
        "Reconciliation: %d matched, %d breaks, %d unmatched",
        matched, breaks, unmatched,
    )
    context.add_output_metadata({
        "matched_count": int(matched),
        "break_count": int(breaks),
        "unmatched_count": int(unmatched),
    })
    return df
