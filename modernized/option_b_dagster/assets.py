"""Dagster assets for trade processing pipeline.

Each asset represents a stage in the trade processing workflow,
using the shared common layer for parsing, validation, enrichment,
and reconciliation.
"""

import pandas as pd
from dagster import AssetExecutionContext, RetryPolicy, asset

from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades
from modernized.option_b_dagster.resources import TradeFileResource

_retry_policy = RetryPolicy(max_retries=3, delay=60)


@asset(retry_policy=_retry_policy)
def raw_trades(context: AssetExecutionContext, trade_files: TradeFileResource) -> pd.DataFrame:
    """Load raw trades from the daily CSV file."""
    filepath = trade_files.trade_file_path
    df = load_trades_csv(filepath)
    context.log.info(f"Loaded {len(df)} trade rows from {filepath}")
    context.add_output_metadata({"row_count": len(df)})
    return df


@asset(retry_policy=_retry_policy)
def validated_trades(
    context: AssetExecutionContext, raw_trades: pd.DataFrame
) -> pd.DataFrame:
    """Validate trades using Pydantic models and broker whitelist."""
    valid_df, error_df = validate_trades(raw_trades)
    error_count = len(error_df)
    valid_count = len(valid_df)
    context.log.info(f"Validation complete: {valid_count} valid, {error_count} errors")
    context.add_output_metadata({
        "valid_count": valid_count,
        "error_count": error_count,
    })
    return valid_df


@asset(retry_policy=_retry_policy)
def enriched_trades(
    context: AssetExecutionContext, validated_trades: pd.DataFrame
) -> pd.DataFrame:
    """Calculate gross/net amounts and fix missing settlement dates."""
    df = validated_trades.copy()

    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    df["net_amount"] = df.apply(
        lambda row: round(row["gross_amount"] + row["commission"], 2)
        if row["side"].strip().upper() == "BUY"
        else round(row["gross_amount"] - row["commission"], 2),
        axis=1,
    )

    missing_settle = df["settle_date"].isna()
    missing_count = int(missing_settle.sum())
    if missing_count > 0:
        df.loc[missing_settle, "settle_date"] = df.loc[missing_settle, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )
        context.log.info(f"Fixed {missing_count} missing settlement dates via T+2")

    context.log.info(
        f"Enriched {len(df)} trades with gross/net amounts and settlement dates"
    )
    context.add_output_metadata({
        "row_count": len(df),
        "settlement_dates_fixed": missing_count,
    })
    return df


@asset(retry_policy=_retry_policy)
def counterparty_confirms(
    context: AssetExecutionContext, trade_files: TradeFileResource
) -> pd.DataFrame:
    """Load counterparty confirmation records from fixed-width file."""
    filepath = trade_files.confirm_file_path
    df = load_counterparty_file(filepath)
    context.log.info(f"Loaded {len(df)} counterparty confirms from {filepath}")
    context.add_output_metadata({"row_count": len(df)})
    return df


@asset(retry_policy=_retry_policy)
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
        suffixes=("", "_confirm"),
    )

    def determine_recon_status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(row["price"] - row["price_confirm"]) > 0.01:
            return "PRICE_BREAK"
        if row["quantity"] != row.get("quantity_confirm"):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(determine_recon_status, axis=1)

    matched = int((merged["recon_status"] == "MATCHED").sum())
    price_breaks = int((merged["recon_status"] == "PRICE_BREAK").sum())
    qty_breaks = int((merged["recon_status"] == "QTY_BREAK").sum())
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())

    context.log.info(
        f"Reconciliation: {matched} matched, {price_breaks} price breaks, "
        f"{qty_breaks} qty breaks, {unmatched} unmatched"
    )
    context.add_output_metadata({
        "matched_count": matched,
        "price_breaks": price_breaks,
        "qty_breaks": qty_breaks,
        "unmatched_count": unmatched,
    })
    return merged
