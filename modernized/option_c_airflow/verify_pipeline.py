"""Standalone verification harness for the Option C task callables.

Runs the per-stage task callables directly (no Airflow scheduler required)
against the committed test data and prints the resulting summary. Intended to be
run from the repo root::

    python -m modernized.option_c_airflow.verify_pipeline
"""

from __future__ import annotations

import logging

from modernized.option_c_airflow.tasks import trade_tasks

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

EXECUTION_DATE = "2024-01-15"


def main() -> int:
    """Run the pipeline against the test data and check the expected summary."""
    result = trade_tasks.run_pipeline(execution_date=EXECUTION_DATE)
    summary = result.model_dump()

    line = (
        f"total_loaded={summary['total_loaded']} "
        f"duplicates_removed={summary['duplicates_removed']} "
        f"validation_errors={summary['validation_errors']} "
        f"matched={summary['matched']} "
        f"breaks={summary['breaks']} "
        f"unmatched={summary['unmatched']}"
    )
    print("SUMMARY:", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
