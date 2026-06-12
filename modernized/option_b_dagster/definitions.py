"""Dagster ``Definitions`` for the Option B trade-processing asset graph.

Combines the assets, the :class:`TradeFileResource`, the daily partition
definition, and the retry policy into a single code location that ``dagster dev``
(or the ``dagster asset materialize`` CLI) can load.

The :data:`DAILY_PARTITIONS` partition set and the
:data:`RetryPolicy(max_retries=3, delay=60)` are defined in
:mod:`modernized.option_b_dagster.assets` and applied to every ``@asset`` there;
they are re-exported here so the code location advertises them explicitly.
"""

from __future__ import annotations

from dagster import Definitions, load_assets_from_modules

from modernized.option_b_dagster import assets
from modernized.option_b_dagster.assets import DAILY_PARTITIONS, RETRY_POLICY
from modernized.option_b_dagster.resources import TradeFileResource

# Daily-partitioned assets; each carries RETRY_POLICY via its @asset decorator.
all_assets = load_assets_from_modules([assets])

defs = Definitions(
    assets=all_assets,
    resources={"trade_files": TradeFileResource()},
)

__all__ = ["defs", "DAILY_PARTITIONS", "RETRY_POLICY"]
