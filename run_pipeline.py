#!/usr/bin/env python
"""Command-line entrypoint for the daily trade pipeline.

Usage::

    python run_pipeline.py              # uses today's date
    python run_pipeline.py 20240315     # specific date

Replaces ``legacy_scripts/daily_batch.py`` with Prefect-managed execution.
"""

from __future__ import annotations

import logging
import sys

from dags.trade_pipeline import daily_trade_pipeline


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_date = sys.argv[1] if len(sys.argv) > 1 else None
    daily_trade_pipeline(run_date=run_date)


if __name__ == "__main__":
    main()
