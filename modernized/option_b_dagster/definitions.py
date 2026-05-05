"""Dagster Definitions entry point for the trade processing pipeline.

This module creates the Definitions object that Dagster uses to discover
and serve assets, resources, and schedules.

Usage:
    dagster dev -m modernized.option_b_dagster.definitions
"""

from __future__ import annotations

from dagster import Definitions, ScheduleDefinition, define_asset_job

from modernized.option_b_dagster.assets import (
    counterparty_confirms,
    daily_partitions,
    enriched_trades,
    raw_trades,
    reconciled_trades,
    validated_trades,
)
from modernized.option_b_dagster.resources import TradeFileResource

trade_processing_job = define_asset_job(
    name="trade_processing_job",
    selection=[
        raw_trades,
        validated_trades,
        enriched_trades,
        counterparty_confirms,
        reconciled_trades,
    ],
    partitions_def=daily_partitions,
)

trade_processing_schedule = ScheduleDefinition(
    job=trade_processing_job,
    cron_schedule="30 6 * * 1-5",  # 6:30 AM weekdays
    name="daily_trade_processing",
)

defs = Definitions(
    assets=[
        raw_trades,
        validated_trades,
        enriched_trades,
        counterparty_confirms,
        reconciled_trades,
    ],
    resources={
        "trade_files": TradeFileResource(
            config_path="config/batch_config.ini",
            base_dir=".",
        ),
    },
    schedules=[trade_processing_schedule],
)
