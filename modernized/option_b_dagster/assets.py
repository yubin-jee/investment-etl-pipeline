"""Dagster assets expressing the trade-processing pipeline as an asset graph.

Each asset is a thin orchestration layer over ``modernized.common`` so that the
business logic stays identical to the other modernization options. Assets are
partitioned by trade date; the partition key selects the input files via
:class:`modernized.option_b_dagster.resources.TradeFileResource`.

Pipeline stages (one asset each):

1. ``raw_trades`` – load the daily trade CSV.
2. ``validated_trades`` – drop duplicates + validate against ``RawTrade``.
3. ``enriched_trades`` – compute gross/net amounts and fill settlement dates.
4. ``counterparty_confirms`` – parse the fixed-width broker confirmations.
5. ``reconciled_trades`` – left-merge, classify breaks, write the report CSV.
"""

import pandas as pd
from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
    MetadataValue,
    Output,
    RetryPolicy,
    asset,
)

from modernized.common import models, parsers, settlement, validation
from modernized.option_b_dagster.resources import TradeFileResource

# Numeric tolerance for a price match (USD), per the shared reconciliation spec.
PRICE_TOLERANCE = 0.01

# Daily partitioning keyed by trade date; the committed sample is 2024-01-15.
DAILY_PARTITIONS = DailyPartitionsDefinition(start_date="2024-01-01")

# Retry transient failures (e.g. a network drive briefly unavailable).
RETRY_POLICY = RetryPolicy(max_retries=3, delay=60)

# Common decorator kwargs applied to every asset in the graph.
_ASSET_KWARGS = {
    "group_name": "trade_pipeline",
    "partitions_def": DAILY_PARTITIONS,
    "retry_policy": RETRY_POLICY,
}

# Final report column order (uppercase headers).
REPORT_COLUMNS = [
    "TRADE_ID",
    "ACCT_NUM",
    "TICKER",
    "SIDE",
    "QTY",
    "PRICE",
    "GROSS_AMT",
    "NET_AMT",
    "COMMISSION",
    "TRADE_DATE",
    "SETTLE_DATE",
    "BROKER",
    "STATUS",
    "RECON_STATUS",
]


@asset(**_ASSET_KWARGS)
def raw_trades(
    context: AssetExecutionContext, trade_files: TradeFileResource
) -> Output[pd.DataFrame]:
    """Load the daily trade CSV for the current partition.

    Args:
        context: Dagster execution context (provides the partition key + log).
        trade_files: Resource that resolves the partition's input file paths.

    Returns:
        The raw trades DataFrame, with ``total_loaded`` attached as metadata.
    """
    partition_key = context.partition_key
    trade_file = trade_files.trade_file(partition_key)
    context.log.info("Loading trades for %s from %s", partition_key, trade_file)

    df = parsers.load_trades_csv(trade_file)
    total_loaded = len(df)
    df.attrs["total_loaded"] = total_loaded

    context.log.info("Loaded %d raw trade rows", total_loaded)
    return Output(
        df,
        metadata={
            "total_loaded": total_loaded,
            "source_file": MetadataValue.path(str(trade_file)),
            "preview": MetadataValue.md(df.head().to_markdown(index=False)),
        },
    )


@asset(**_ASSET_KWARGS)
def validated_trades(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
    raw_trades: pd.DataFrame,
) -> Output[pd.DataFrame]:
    """Validate raw trades, dropping duplicates and invalid rows.

    Writes an error log CSV listing every rejected row and its
    ``error_reason``. Validation statistics are logged and carried forward via
    DataFrame ``attrs`` for the final :class:`ProcessingResult`.

    Args:
        context: Dagster execution context.
        trade_files: Resource used to resolve the error-log output path.
        raw_trades: The upstream raw trades DataFrame.

    Returns:
        The valid trades DataFrame with validation counts in ``attrs``.
    """
    valid, errors = validation.validate_trades(raw_trades)

    if not errors.empty:
        duplicates_removed = int((errors["error_reason"] == "DUPLICATE").sum())
    else:
        duplicates_removed = 0
    validation_errors = int(len(errors) - duplicates_removed)

    total_loaded = int(raw_trades.attrs.get("total_loaded", len(raw_trades)))

    valid.attrs["total_loaded"] = total_loaded
    valid.attrs["duplicates_removed"] = duplicates_removed
    valid.attrs["validation_errors"] = validation_errors

    # Persist the error log so operators can inspect rejected rows.
    error_log_path = trade_files.error_log_path(context.partition_key)
    with error_log_path.open("w", newline="", encoding="utf-8") as handle:
        errors.to_csv(handle, index=False)

    context.log.info(
        "Validation: %d valid, %d duplicates removed, %d validation errors",
        len(valid),
        duplicates_removed,
        validation_errors,
    )
    return Output(
        valid,
        metadata={
            "valid_rows": len(valid),
            "duplicates_removed": duplicates_removed,
            "validation_errors": validation_errors,
            "error_log": MetadataValue.path(str(error_log_path)),
        },
    )


@asset(**_ASSET_KWARGS)
def enriched_trades(
    context: AssetExecutionContext, validated_trades: pd.DataFrame
) -> Output[pd.DataFrame]:
    """Compute gross/net amounts and fill missing settlement dates.

    * ``gross_amount = round(quantity * price, 2)``
    * ``net_amount`` adds commission for BUY and subtracts it for SELL.
    * Missing (``NaT``) settle dates are filled with the T+2 business day.

    Args:
        context: Dagster execution context.
        validated_trades: The upstream valid trades DataFrame.

    Returns:
        The enriched trades DataFrame (validation counts preserved in ``attrs``).
    """
    df = validated_trades.copy()
    df.attrs.update(validated_trades.attrs)

    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    is_buy = df["side"] == "BUY"
    df["net_amount"] = (
        df["gross_amount"] + df["commission"].where(is_buy, -df["commission"])
    ).round(2)

    missing_settle = df["settle_date"].isna()
    if missing_settle.any():
        df.loc[missing_settle, "settle_date"] = df.loc[
            missing_settle, "trade_date"
        ].apply(
            lambda ts: pd.Timestamp(settlement.calculate_t_plus_2(ts.date()))
        )

    context.log.info(
        "Enriched %d trades; filled %d missing settle dates",
        len(df),
        int(missing_settle.sum()),
    )
    return Output(
        df,
        metadata={
            "enriched_rows": len(df),
            "settle_dates_filled": int(missing_settle.sum()),
            "gross_total": float(df["gross_amount"].sum()),
        },
    )


@asset(**_ASSET_KWARGS)
def counterparty_confirms(
    context: AssetExecutionContext, trade_files: TradeFileResource
) -> Output[pd.DataFrame]:
    """Parse the fixed-width counterparty confirmation file for the partition.

    Args:
        context: Dagster execution context.
        trade_files: Resource that resolves the confirmation file path.

    Returns:
        The confirmations DataFrame (``T-`` records only).
    """
    confirm_file = trade_files.confirm_file(context.partition_key)
    context.log.info("Loading confirms from %s", confirm_file)

    df = parsers.load_counterparty_file(confirm_file)
    context.log.info("Loaded %d counterparty confirmations", len(df))
    return Output(
        df,
        metadata={
            "confirm_rows": len(df),
            "source_file": MetadataValue.path(str(confirm_file)),
        },
    )


def _classify_recon(row: pd.Series) -> str:
    """Classify a merged trade/confirm row into a reconciliation status."""
    if pd.isna(row["price_confirm"]):
        return "UNMATCHED"
    if abs(float(row["price"]) - float(row["price_confirm"])) > PRICE_TOLERANCE:
        return "PRICE_BREAK"
    if pd.isna(row["quantity_confirm"]) or int(row["quantity"]) != int(
        row["quantity_confirm"]
    ):
        return "QTY_BREAK"
    return "MATCHED"


def _build_report(merged: pd.DataFrame) -> pd.DataFrame:
    """Build the uppercase-header report DataFrame with MM/DD/YYYY dates."""
    report = pd.DataFrame(
        {
            "TRADE_ID": merged["trade_id"],
            "ACCT_NUM": merged["account"],
            "TICKER": merged["ticker"],
            "SIDE": merged["side"],
            "QTY": merged["quantity"],
            "PRICE": merged["price"],
            "GROSS_AMT": merged["gross_amount"],
            "NET_AMT": merged["net_amount"],
            "COMMISSION": merged["commission"],
            "TRADE_DATE": merged["trade_date"].dt.strftime("%m/%d/%Y"),
            "SETTLE_DATE": merged["settle_date"].dt.strftime("%m/%d/%Y"),
            "BROKER": merged["broker"],
            "STATUS": merged["status"],
            "RECON_STATUS": merged["recon_status"],
        }
    )
    return report[REPORT_COLUMNS]


@asset(**_ASSET_KWARGS)
def reconciled_trades(
    context: AssetExecutionContext,
    trade_files: TradeFileResource,
    enriched_trades: pd.DataFrame,
    counterparty_confirms: pd.DataFrame,
) -> Output[pd.DataFrame]:
    """Reconcile enriched trades against confirmations and write the report.

    Performs a LEFT merge on ``trade_id``, classifies each row
    (``MATCHED`` / ``PRICE_BREAK`` / ``QTY_BREAK`` / ``UNMATCHED``), writes the
    report CSV, and produces a fully-populated :class:`ProcessingResult`.

    Args:
        context: Dagster execution context.
        trade_files: Resource that resolves the report output path.
        enriched_trades: The upstream enriched trades DataFrame.
        counterparty_confirms: The upstream confirmations DataFrame.

    Returns:
        The reconciled report DataFrame, with the full ``ProcessingResult``
        summary attached as metadata.
    """
    merged = enriched_trades.merge(
        counterparty_confirms,
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )
    merged["recon_status"] = merged.apply(_classify_recon, axis=1)

    counts = merged["recon_status"].value_counts()
    matched = int(counts.get("MATCHED", 0))
    breaks = int(counts.get("PRICE_BREAK", 0) + counts.get("QTY_BREAK", 0))
    unmatched = int(counts.get("UNMATCHED", 0))

    report = _build_report(merged)
    report_path = trade_files.report_path(context.partition_key)
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        report.to_csv(handle, index=False)

    result = models.ProcessingResult(
        total_loaded=int(enriched_trades.attrs.get("total_loaded", 0)),
        duplicates_removed=int(enriched_trades.attrs.get("duplicates_removed", 0)),
        validation_errors=int(enriched_trades.attrs.get("validation_errors", 0)),
        matched=matched,
        breaks=breaks,
        unmatched=unmatched,
    )

    context.log.info(
        "Reconciliation summary: total_loaded=%d duplicates_removed=%d "
        "validation_errors=%d matched=%d breaks=%d unmatched=%d",
        result.total_loaded,
        result.duplicates_removed,
        result.validation_errors,
        result.matched,
        result.breaks,
        result.unmatched,
    )
    return Output(
        report,
        metadata={
            "report_file": MetadataValue.path(str(report_path)),
            "total_loaded": result.total_loaded,
            "duplicates_removed": result.duplicates_removed,
            "validation_errors": result.validation_errors,
            "matched": result.matched,
            "breaks": result.breaks,
            "unmatched": result.unmatched,
            "summary": MetadataValue.json(result.model_dump()),
            "preview": MetadataValue.md(report.to_markdown(index=False)),
        },
    )
