#!/usr/bin/env python
"""
Daily Batch Runner - Meridian Capital Partners
Runs all daily processing scripts in sequence.

This is called by the scheduler every morning. If any step fails, Sandra gets
an email (configured in the scheduler).

Author: Mike Torres

KNOWN ISSUES:
- If trade file is late, this script fails and someone has to manually re-run it
- No retry logic
- If market prices file isn't ready, NAV calc uses stale prices
- Compliance check runs against yesterday's positions (not today's)
  because positions file isn't updated until after this runs
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from logging_config import get_logger

log = get_logger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent


def run_step(script_name: str, run_date: str) -> int:
    """Run one pipeline step as a subprocess and return its exit code."""
    result = subprocess.run([sys.executable, str(SCRIPT_DIR / script_name), run_date])
    return result.returncode


def main(argv: list[str]) -> None:
    # figure out today's date, allow override from command line
    today = argv[1] if len(argv) > 1 else datetime.now().strftime("%Y%m%d")

    log.info("*" * 60)
    log.info("* MERIDIAN CAPITAL - DAILY BATCH PROCESSING")
    log.info(f"* Date: {today}")
    log.info("* Start Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("*" * 60)

    # Step 1: Process Trades
    log.info("\n\n>>> STEP 1: TRADE PROCESSING <<<")
    log.info("-" * 40)
    start = time.time()
    ret = run_step("process_trades.py", today)
    log.info(f"Trade processing took {time.time() - start:.1f} seconds")
    if ret != 0:
        log.info("*** TRADE PROCESSING FAILED ***")
        # don't exit - try to continue with other steps
        # Sandra will fix it manually

    # Step 2: NAV Calculation
    log.info("\n\n>>> STEP 2: NAV CALCULATION <<<")
    log.info("-" * 40)
    start = time.time()
    ret = run_step("calc_nav.py", today)
    log.info(f"NAV calc took {time.time() - start:.1f} seconds")
    if ret != 0:
        log.info("*** NAV CALCULATION FAILED ***")

    # Step 3: Reconciliation
    log.info("\n\n>>> STEP 3: POSITION RECONCILIATION <<<")
    log.info("-" * 40)
    start = time.time()
    ret = run_step("reconciliation.py", today)
    log.info(f"Reconciliation took {time.time() - start:.1f} seconds")
    if ret != 0:
        log.info("*** RECONCILIATION FAILED - BREAKS FOUND ***")
        log.info("*** Sandra: Please review recon report ***")

    # Step 4: Compliance
    log.info("\n\n>>> STEP 4: COMPLIANCE CHECK <<<")
    log.info("-" * 40)
    start = time.time()
    ret = run_step("compliance_check.py", today)
    log.info(f"Compliance check took {time.time() - start:.1f} seconds")
    if ret != 0:
        log.info("*** COMPLIANCE VIOLATIONS FOUND ***")

    # Step 5: Client Reports (only on month-end)
    # TODO: actually check if it's month end
    # For now just always generate
    log.info("\n\n>>> STEP 5: CLIENT REPORTS <<<")
    log.info("-" * 40)
    start = time.time()
    ret = run_step("generate_client_reports.py", today)
    log.info(f"Report generation took {time.time() - start:.1f} seconds")

    # Done
    log.info("\n\n" + "*" * 60)
    log.info("* DAILY BATCH COMPLETE")
    log.info("* End Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("*" * 60)


if __name__ == "__main__":
    main(sys.argv)
