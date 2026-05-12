"""Prefect flow for the daily trade processing pipeline.

Replaces the ``os.system()`` sequential calls in ``legacy_scripts/daily_batch.py``
with a proper DAG that has retry logic, structured logging, and explicit data
dependencies between tasks.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd
from prefect import flow, task
from prefect.tasks import task_input_hash

from trade_ingestion.loaders.csv_loader import load_daily_trades
from trade_ingestion.loaders.fixedwidth_loader import load_confirms
from trade_ingestion.reconciliation import reconcile
from trade_ingestion.transforms import calculate_amounts, fill_settlement_dates
from trade_ingestion.validators import validate_trades

logger = logging.getLogger(__name__)


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def load_trades_task(run_date: str) -> pd.DataFrame:
    """Load daily trade CSV for the given date."""
    logger.info("Loading trades for %s", run_date)
    df = load_daily_trades(run_date)
    if df.empty:
        logger.warning("No trades found for %s", run_date)
    return df


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def validate_trades_task(
    trades_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Validate trade rows via pydantic models."""
    logger.info("Validating %d trade rows", len(trades_df))
    valid_df, errors = validate_trades(trades_df)
    if errors:
        logger.warning("%d validation errors found", len(errors))
    return valid_df, errors


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def calculate_amounts_task(valid_df: pd.DataFrame) -> pd.DataFrame:
    """Enrich trades with gross/net amounts and settlement dates."""
    logger.info("Calculating amounts for %d trades", len(valid_df))
    enriched = fill_settlement_dates(valid_df)
    enriched = calculate_amounts(enriched)
    return enriched


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def load_confirms_task(run_date: str) -> pd.DataFrame:
    """Load counterparty confirmation file."""
    logger.info("Loading confirmations for %s", run_date)
    return load_confirms()


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def reconcile_task(
    enriched_df: pd.DataFrame, confirms_df: pd.DataFrame
) -> pd.DataFrame:
    """Reconcile internal trades against counterparty confirmations."""
    logger.info(
        "Reconciling %d trades against %d confirms",
        len(enriched_df),
        len(confirms_df),
    )
    return reconcile(enriched_df, confirms_df)


@task(retries=3, retry_delay_seconds=[10, 30, 60], log_prints=True)
def write_to_db_task(reconciled_df: pd.DataFrame) -> int:
    """Upsert reconciled trades into the database."""
    from trade_ingestion.db import upsert_trades

    logger.info("Writing %d reconciled trades to database", len(reconciled_df))
    return upsert_trades(reconciled_df)


@flow(name="daily-trade-pipeline", log_prints=True)
def daily_trade_pipeline(run_date: str | None = None) -> pd.DataFrame:
    """End-to-end daily trade processing pipeline.

    Parameters
    ----------
    run_date : str, optional
        Date string in ``YYYYMMDD`` format.  Defaults to today.

    Returns
    -------
    pd.DataFrame
        Reconciled trades DataFrame.
    """
    if run_date is None:
        run_date = datetime.now().strftime("%Y%m%d")

    logger.info("=== Daily Trade Pipeline — %s ===", run_date)

    trades_df = load_trades_task(run_date)
    valid_df, errors = validate_trades_task(trades_df)
    enriched_df = calculate_amounts_task(valid_df)

    confirms_df = load_confirms_task(run_date)
    reconciled_df = reconcile_task(enriched_df, confirms_df)

    try:
        inserted = write_to_db_task(reconciled_df)
        logger.info("Database upsert complete — %d rows inserted", inserted)
    except Exception:
        logger.exception(
            "Database write failed — pipeline results available in-memory only"
        )

    logger.info("=== Pipeline complete — %d trades processed ===", len(reconciled_df))
    return reconciled_df
