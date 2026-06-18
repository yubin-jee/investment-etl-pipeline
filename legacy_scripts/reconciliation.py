#!/usr/bin/env python
"""
Position Reconciliation Script - Meridian Capital Partners
Compares internal positions with custodian (State Street) positions

Author: Mike Torres
NOTE: Custodian file format changed in 2023 and this script was patched
      by Dave in ops. The parsing is fragile - do not change column positions.

Last Modified: 2023-02-17
"""

import csv
import os
import re
import sys
from datetime import datetime

# custodian rows: ACCOUNT  SECURITY NAME  CUSIP(9 alnum or ---)  QTY  PRICE  MKT_VALUE
# whitespace-tolerant so misaligned source rows still parse correctly
CUSTODIAN_ROW_RE = re.compile(
    r"^(?P<acct>\S+)\s+(?P<name>.+?)\s+(?P<cusip>[0-9A-Z]{9}|-+)\s+"
    r"(?P<qty>[\d,]+)\s+(?P<price>[\d,.]+)\s+(?P<mktval>[\d,.]+)\s*$"
)

# paths
HOLDINGS_DIR = "C:\\MeridianData\\holdings\\"
OUTPUT_DIR = "C:\\MeridianData\\reports\\"

# tolerance for matching (in dollars)
TOLERANCE = 1.00  # $1 tolerance - Sandra requested this after too many false breaks

internal_positions = {}
custodian_positions = {}
recon_results = []


def load_internal_positions(date_str):
    """load our internal position file"""
    global internal_positions
    file_path = HOLDINGS_DIR + "portfolio_positions_" + date_str + ".csv"

    if not os.path.exists(file_path):
        file_path = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "holdings", "portfolio_positions_" + date_str + ".csv")

    print("Loading internal positions: " + file_path)

    f = open(file_path, "r")
    reader = csv.reader(f)
    next(reader)  # skip header

    for row in reader:
        acct = row[0]
        ticker = row[1]
        qty = int(row[4]) if row[4] else 0
        mkt_val = float(row[6]) if row[6] else 0.0

        if qty == 0:
            continue

        key = acct + "|" + ticker
        internal_positions[key] = {
            "account": acct,
            "ticker": ticker,
            "quantity": qty,
            "market_value": mkt_val
        }

    f.close()
    print("Loaded " + str(len(internal_positions)) + " internal positions")


def load_custodian_positions(date_str):
    """parse the State Street custodian report
    This is a fixed-width text file with headers and footers.
    Format is fragile - hardcoded column positions.
    """
    global custodian_positions
    file_path = HOLDINGS_DIR + "custodian_positions_" + date_str + ".txt"

    if not os.path.exists(file_path):
        file_path = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "holdings", "custodian_positions_" + date_str + ".txt")

    print("Loading custodian positions: " + file_path)

    f = open(file_path, "r")
    lines = f.readlines()
    f.close()

    for line in lines:
        # skip headers, footers, separator lines
        if line.startswith("=") or line.startswith(" ") or line.startswith("-"):
            continue
        if "ACCOUNT" in line or "TOTAL" in line or "GENERATED" in line or "CLIENT" in line or "AS OF" in line:
            continue
        if len(line.strip()) < 10:
            continue

        # parse columns by structure rather than hardcoded offsets so that
        # rows with slightly misaligned spacing still parse correctly
        m = CUSTODIAN_ROW_RE.match(line)
        if not m:
            continue
        try:
            acct = m.group("acct").strip()
            security_name = m.group("name").strip()
            cusip = m.group("cusip").strip()
            qty_str = m.group("qty").replace(",", "")
            mkt_val_str = m.group("mktval").replace(",", "")

            if not acct or not qty_str:
                continue

            qty = int(qty_str)
            mkt_val = float(mkt_val_str)

            # we need ticker but custodian only gives security name and cusip
            # this is a manual mapping - TERRIBLE but it works
            ticker = cusip_to_ticker(cusip, security_name)

            if ticker:
                key = acct + "|" + ticker
                custodian_positions[key] = {
                    "account": acct,
                    "ticker": ticker,
                    "security_name": security_name,
                    "cusip": cusip,
                    "quantity": qty,
                    "market_value": mkt_val
                }
        except Exception as e:
            print("ERROR parsing custodian line: " + line.strip())
            print("  " + str(e))

    print("Loaded " + str(len(custodian_positions)) + " custodian positions")


def cusip_to_ticker(cusip, security_name):
    """Manual CUSIP to ticker mapping
    TODO: hook this up to the reference data service
    For now just hardcoding the ones we have
    """
    CUSIP_MAP = {
        "037833100": "AAPL",
        "02079K305": "GOOGL",
        "88160R101": "TSLA",
        "742718109": "PG",
        "594918104": "MSFT",
        "67066G104": "NVDA",
        "437076102": "HD",
        "023135106": "AMZN",
        "92826C839": "V",
        "254687106": "DIS",
        "30303M102": "META",
        "91324P102": "UNH",
        "46625H100": "JPM",
        "57636Q104": "MA",
    }

    if cusip in CUSIP_MAP:
        return CUSIP_MAP[cusip]

    # try to guess from security name (this is bad)
    if "VANGUARD" in security_name.upper() and "BOND" in security_name.upper():
        return "BND"
    if "ISHARES" in security_name.upper() and "AGG" in security_name.upper():
        return "AGG"
    if "ISHARES" in security_name.upper() and "TREAS" in security_name.upper():
        return "TLT"

    print("WARNING: Unknown CUSIP " + cusip + " for " + security_name)
    return None


def run_reconciliation():
    """compare internal vs custodian positions"""
    global recon_results
    print("\n" + "=" * 60)
    print("RUNNING RECONCILIATION")
    print("=" * 60)

    all_keys = set(list(internal_positions.keys()) + list(custodian_positions.keys()))

    matched = 0
    breaks = 0
    internal_only = 0
    custodian_only = 0

    for key in sorted(all_keys):
        internal = internal_positions.get(key)
        custodian = custodian_positions.get(key)

        result = {"key": key}

        if internal and custodian:
            # both sides exist - compare
            qty_match = internal["quantity"] == custodian["quantity"]
            val_diff = abs(internal["market_value"] - custodian["market_value"])
            val_match = val_diff <= TOLERANCE

            if qty_match and val_match:
                result["status"] = "MATCHED"
                result["detail"] = ""
                matched = matched + 1
            else:
                result["status"] = "BREAK"
                details = []
                if not qty_match:
                    details.append("QTY: Internal=" + str(internal["quantity"]) + " Custodian=" + str(custodian["quantity"]))
                if not val_match:
                    details.append("VAL: Internal=" + str(internal["market_value"]) + " Custodian=" + str(custodian["market_value"]) + " Diff=" + str(round(val_diff, 2)))
                result["detail"] = "; ".join(details)
                breaks = breaks + 1
                print("  BREAK: " + key + " - " + result["detail"])

            result["internal_qty"] = internal["quantity"]
            result["internal_val"] = internal["market_value"]
            result["custodian_qty"] = custodian["quantity"]
            result["custodian_val"] = custodian["market_value"]

        elif internal and not custodian:
            result["status"] = "INTERNAL_ONLY"
            result["detail"] = "Position exists internally but not at custodian"
            result["internal_qty"] = internal["quantity"]
            result["internal_val"] = internal["market_value"]
            result["custodian_qty"] = 0
            result["custodian_val"] = 0.0
            internal_only = internal_only + 1
            print("  INTERNAL ONLY: " + key)

        elif custodian and not internal:
            result["status"] = "CUSTODIAN_ONLY"
            result["detail"] = "Position exists at custodian but not internally"
            result["internal_qty"] = 0
            result["internal_val"] = 0.0
            result["custodian_qty"] = custodian["quantity"]
            result["custodian_val"] = custodian["market_value"]
            custodian_only = custodian_only + 1
            print("  CUSTODIAN ONLY: " + key)

        recon_results.append(result)

    print("\n  SUMMARY:")
    print("  Matched:        " + str(matched))
    print("  Breaks:         " + str(breaks))
    print("  Internal Only:  " + str(internal_only))
    print("  Custodian Only: " + str(custodian_only))

    return breaks == 0 and internal_only == 0 and custodian_only == 0


def write_recon_report(date_str):
    """write reconciliation report"""
    output_path = OUTPUT_DIR + "recon_report_" + date_str + ".csv"

    if not os.path.exists(OUTPUT_DIR):
        output_path = os.path.join(os.path.dirname(__file__), "..", "reports", "recon_report_" + date_str + ".csv")

    print("\nWriting recon report to: " + output_path)

    f = open(output_path, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(["KEY", "STATUS", "INTERNAL_QTY", "INTERNAL_VALUE",
                      "CUSTODIAN_QTY", "CUSTODIAN_VALUE", "DETAIL", "AS_OF_DATE", "GENERATED_AT"])

    for r in recon_results:
        writer.writerow([
            r["key"], r["status"], r["internal_qty"], r["internal_val"],
            r["custodian_qty"], r["custodian_val"], r["detail"], date_str,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])

    f.close()


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("MERIDIAN CAPITAL - POSITION RECONCILIATION")
    print("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if len(sys.argv) > 1:
        run_date = sys.argv[1]
    else:
        run_date = "20240315"

    load_internal_positions(run_date)
    load_custodian_positions(run_date)

    clean = run_reconciliation()

    write_recon_report(run_date)

    if clean:
        print("\nRECONCILIATION: CLEAN")
        sys.exit(0)
    else:
        print("\nRECONCILIATION: BREAKS FOUND - MANUAL REVIEW REQUIRED")
        sys.exit(1)
