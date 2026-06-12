"""Option B: Dagster asset-graph implementation of the trade pipeline.

Expresses the legacy ``legacy_scripts/process_trades.py`` batch as a partitioned
Dagster asset graph built entirely on top of ``modernized.common``.
"""
