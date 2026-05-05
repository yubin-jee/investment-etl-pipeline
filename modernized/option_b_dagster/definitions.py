"""Dagster entry point — combines assets and resources."""

from dagster import Definitions

from modernized.option_b_dagster.assets import (
    counterparty_confirms,
    enriched_trades,
    raw_trades,
    reconciled_trades,
    validated_trades,
)
from modernized.option_b_dagster.resources import TradeFileResource

defs = Definitions(
    assets=[
        raw_trades,
        validated_trades,
        enriched_trades,
        counterparty_confirms,
        reconciled_trades,
    ],
    resources={
        "trade_files": TradeFileResource(),
    },
)
