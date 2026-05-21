"""Dagster Definitions for the trade processing pipeline.

Launch with:
    dagster dev -m modernized.option_b_dagster.definitions
"""

from pathlib import Path

from dagster import Definitions

from modernized.option_b_dagster.assets import (
    counterparty_confirms,
    enriched_trades,
    raw_trades,
    reconciled_trades,
    validated_trades,
)
from modernized.option_b_dagster.resources import TradeFileResource

_repo_root = Path(__file__).resolve().parents[2]

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
            base_dir=str(_repo_root / "modernized" / "test_data"),
            config_path=str(_repo_root / "config" / "batch_config.ini"),
        ),
    },
)
