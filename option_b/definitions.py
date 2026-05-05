"""Dagster Definitions — wire up assets and resources.

Launch with: dagster dev -m option_b.definitions
"""

from dagster import Definitions

from option_b.assets import (
    enriched_trades,
    raw_confirms,
    raw_trades,
    reconciled_trades,
    trade_output,
    validated_trades,
)
from option_b.resources import FilePathResource

defs = Definitions(
    assets=[
        raw_trades,
        raw_confirms,
        validated_trades,
        enriched_trades,
        reconciled_trades,
        trade_output,
    ],
    resources={
        "file_paths": FilePathResource(),
    },
)
