#!/usr/bin/env python
"""
Daily Batch Runner - Meridian Capital Partners
Runs all daily processing scripts in sequence

Scheduled via cron / a container scheduler (see deploy/crontab and the
[schedule] cron expressions in config/batch_config.ini), not Task Scheduler.

Author: Mike Torres
Last Modified: 2022-09-01

KNOWN ISSUES:
- If trade file is late (after 6:30 AM), this script fails and
  someone has to manually re-run it
- No retry logic
- If market prices file isn't ready, NAV calc uses stale prices
- Compliance check runs against yesterday's positions (not today's)
  because positions file isn't updated until after this runs
"""

import os
import sys
import time
from datetime import datetime

# figure out today's date
today = datetime.now().strftime("%Y%m%d")

# allow override from command line
if len(sys.argv) > 1:
    today = sys.argv[1]

print("*" * 60)
print("* MERIDIAN CAPITAL - DAILY BATCH PROCESSING")
print("* Date: " + today)
print("* Start Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("*" * 60)

script_dir = os.path.dirname(os.path.abspath(__file__))

# Step 1: Process Trades
print("\n\n>>> STEP 1: TRADE PROCESSING <<<")
print("-" * 40)
start = time.time()
ret = os.system("python " + os.path.join(script_dir, "process_trades.py") + " " + today)
elapsed = time.time() - start
print("Trade processing took {:.1f} seconds".format(elapsed))
if ret != 0:
    print("*** TRADE PROCESSING FAILED ***")
    # don't exit - try to continue with other steps
    # Sandra will fix it manually

# Step 2: NAV Calculation
print("\n\n>>> STEP 2: NAV CALCULATION <<<")
print("-" * 40)
start = time.time()
ret = os.system("python " + os.path.join(script_dir, "calc_nav.py") + " " + today)
elapsed = time.time() - start
print("NAV calc took {:.1f} seconds".format(elapsed))
if ret != 0:
    print("*** NAV CALCULATION FAILED ***")

# Step 3: Reconciliation
print("\n\n>>> STEP 3: POSITION RECONCILIATION <<<")
print("-" * 40)
start = time.time()
ret = os.system("python " + os.path.join(script_dir, "reconciliation.py") + " " + today)
elapsed = time.time() - start
print("Reconciliation took {:.1f} seconds".format(elapsed))
if ret != 0:
    print("*** RECONCILIATION FAILED - BREAKS FOUND ***")
    print("*** Sandra: Please review recon report ***")

# Step 4: Compliance
print("\n\n>>> STEP 4: COMPLIANCE CHECK <<<")
print("-" * 40)
start = time.time()
ret = os.system("python " + os.path.join(script_dir, "compliance_check.py") + " " + today)
elapsed = time.time() - start
print("Compliance check took {:.1f} seconds".format(elapsed))
if ret != 0:
    print("*** COMPLIANCE VIOLATIONS FOUND ***")

# Step 5: Client Reports (only on month-end)
# TODO: actually check if it's month end
# For now just always generate
print("\n\n>>> STEP 5: CLIENT REPORTS <<<")
print("-" * 40)
start = time.time()
ret = os.system("python " + os.path.join(script_dir, "generate_client_reports.py") + " " + today)
elapsed = time.time() - start
print("Report generation took {:.1f} seconds".format(elapsed))

# Done
print("\n\n" + "*" * 60)
print("* DAILY BATCH COMPLETE")
print("* End Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("*" * 60)
