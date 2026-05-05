"""Dagster software-defined assets for trade processing pipeline."""

import logging
from datetime import datetime

import pandas as pd
from dagster import AssetExecutionContext, asset

from option_b.resources import FilePathResource
from trade_processing.calculators import calculate_amounts
from trade_processing.loaders.csv_loader import load_trades
from trade_processing.loaders.fwf_loader import load_confirms
from trade_processing.reconciliation import reconcile
from trade_processing.settlement import calculate_settlement_dates
from trade_processing.validators import validate

logger = logging.getLogger("option_b")


@asset(description="Raw trades loaded from CSV file")
def raw_trades(context: AssetExecutionContext, file_paths: FilePathResource) -> pd.DataFrame:
    df = load_trades(file_paths.trade_path)
    context.log.info("Loaded %d raw trades", len(df))
    return df


@asset(description="Raw counterparty confirmations loaded from fixed-width file")
def raw_confirms(context: AssetExecutionContext, file_paths: FilePathResource) -> pd.DataFrame:
    df = load_confirms(file_paths.confirm_path)
    context.log.info("Loaded %d confirms", len(df))
    return df


@asset(description="Validated trades with rejected trades filtered out")
def validated_trades(context: AssetExecutionContext, raw_trades: pd.DataFrame) -> pd.DataFrame:
    valid_df, rejected_df = validate(raw_trades)
    context.log.info("Validated: %d valid, %d rejected", len(valid_df), len(rejected_df))
    return valid_df


@asset(description="Trades enriched with correct settlement dates and calculated amounts")
def enriched_trades(context: AssetExecutionContext, validated_trades: pd.DataFrame) -> pd.DataFrame:
    df = calculate_settlement_dates(validated_trades)
    df = calculate_amounts(df)
    context.log.info("Enriched %d trades with settlement dates and amounts", len(df))
    return df


@asset(description="Trades reconciled with counterparty confirmations")
def reconciled_trades(
    context: AssetExecutionContext,
    enriched_trades: pd.DataFrame,
    raw_confirms: pd.DataFrame,
) -> pd.DataFrame:
    df = reconcile(enriched_trades, raw_confirms)
    status_counts = df["recon_status"].value_counts().to_dict()
    context.log.info("Reconciliation results: %s", status_counts)
    return df


@asset(description="Final output written to CSV")
def trade_output(
    context: AssetExecutionContext,
    reconciled_trades: pd.DataFrame,
    file_paths: FilePathResource,
) -> pd.DataFrame:
    output_dir = file_paths.output_path
    reconciled_trades["processed_at"] = datetime.now().isoformat()
    output_file = output_dir / "processed_trades.csv"
    reconciled_trades.to_csv(output_file, index=False)
    context.log.info("Wrote %d trades to %s", len(reconciled_trades), output_file)
    return reconciled_trades
