"""Standalone verification harness for the Option B asset graph.

Materializes every asset for a single partition (default ``2024-01-15``) using
Dagster's in-process executor and prints the reconciliation summary so the
pipeline can be validated without launching the webserver.

Run from the repo root::

    python -m modernized.option_b_dagster.verify
"""

from __future__ import annotations

import argparse
import logging

from dagster import materialize

from modernized.option_b_dagster.assets import (
    counterparty_confirms,
    enriched_trades,
    raw_trades,
    reconciled_trades,
    validated_trades,
)
from modernized.option_b_dagster.resources import TradeFileResource

logger = logging.getLogger(__name__)

ASSETS = [
    raw_trades,
    validated_trades,
    enriched_trades,
    counterparty_confirms,
    reconciled_trades,
]


def run(partition_key: str = "2024-01-15") -> dict[str, int]:
    """Materialize all assets for ``partition_key`` and return the summary.

    Args:
        partition_key: The daily partition to materialize.

    Returns:
        A dict of the six ``ProcessingResult`` summary counts.

    Raises:
        RuntimeError: If materialization fails.
    """
    result = materialize(
        ASSETS,
        partition_key=partition_key,
        resources={"trade_files": TradeFileResource()},
    )
    if not result.success:
        raise RuntimeError("Materialization failed")

    metadata = result.asset_materializations_for_node("reconciled_trades")[
        0
    ].metadata
    summary = {
        key: int(metadata[key].value)
        for key in (
            "total_loaded",
            "duplicates_removed",
            "validation_errors",
            "matched",
            "breaks",
            "unmatched",
        )
    }
    return summary


def main() -> None:
    """CLI entrypoint: materialize one partition and print the summary line."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", default="2024-01-15")
    args = parser.parse_args()

    summary = run(args.partition)
    line = " ".join(f"{key}={value}" for key, value in summary.items())
    logger.info("RECONCILIATION SUMMARY: %s", line)
    print(line)


if __name__ == "__main__":
    main()
