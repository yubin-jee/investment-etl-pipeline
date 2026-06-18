#!/usr/bin/env python
"""
Compliance Check Script - Meridian Capital Partners
Checks portfolio positions against compliance rules

Author: Lisa Park / Dave Ops
NOTE: Rules are loaded from XML because that's what the old
      compliance vendor used. Nobody knows why it's XML.

Last Modified: 2023-01-09
"""

import csv
import os
import sys
from datetime import datetime
try:
    import xml.etree.ElementTree as ET
except:
    print("ERROR: xml module not found")
    sys.exit(1)

import etl_config

# OS-agnostic, configurable paths (see etl_config / batch_config.ini / .env)
COMPLIANCE_DIR = etl_config.COMPLIANCE_DIR
HOLDINGS_DIR = etl_config.HOLDINGS_DIR
CLIENTS_DIR = etl_config.CLIENTS_DIR
OUTPUT_DIR = etl_config.REPORT_DIR

rules = []
violations = []


def load_rules():
    """load compliance rules from XML file"""
    global rules
    file_path = str(COMPLIANCE_DIR / "compliance_rules.xml")

    print("Loading compliance rules: " + file_path)

    tree = ET.parse(file_path)
    root = tree.getroot()

    for rule_elem in root.findall("Rule"):
        rule = {
            "id": rule_elem.get("id"),
            "severity": rule_elem.get("severity"),
            "name": rule_elem.find("Name").text,
            "description": rule_elem.find("Description").text,
            "threshold": float(rule_elem.find("Threshold").text) if rule_elem.find("Threshold") is not None else None,
            "asset_class": rule_elem.find("AssetClass").text if rule_elem.find("AssetClass") is not None else None,
            "account_types": rule_elem.find("AccountTypes").text.split(",") if rule_elem.find("AccountTypes") is not None else None,
            "action": rule_elem.find("Action").text,
        }
        rules.append(rule)

    print("Loaded " + str(len(rules)) + " rules")


def load_positions_and_clients(date_str):
    """load positions and client data for checking"""
    positions = {}
    clients = {}

    # load positions
    pos_file = str(HOLDINGS_DIR / ("portfolio_positions_" + date_str + ".csv"))
    f = open(pos_file, "r")
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        acct = row[0]
        if acct not in positions:
            positions[acct] = []
        qty = int(row[4]) if row[4] else 0
        mkt_val = float(row[6]) if row[6] else 0.0
        if qty > 0:
            positions[acct].append({
                "ticker": row[1],
                "quantity": qty,
                "market_value": mkt_val,
                "asset_class": row[8],
                "sector": row[9]
            })
    f.close()

    # load clients
    client_file = str(CLIENTS_DIR / "client_master.csv")
    f = open(client_file, "r")
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        clients[row[0]] = {"name": row[1], "type": row[2]}
    f.close()

    return positions, clients


def check_concentration_limits(positions, clients):
    """RULE-001: Single security concentration limit (10%)"""
    global violations
    print("\nChecking RULE-001: Single Security Concentration...")

    for acct in positions:
        total_value = sum([p["market_value"] for p in positions[acct]])
        if total_value == 0:
            continue

        for pos in positions[acct]:
            concentration = pos["market_value"] / total_value
            if concentration > 0.10:
                violation = {
                    "rule_id": "RULE-001",
                    "severity": "CRITICAL",
                    "account": acct,
                    "client": clients.get(acct, {}).get("name", "UNKNOWN"),
                    "detail": pos["ticker"] + " is " + str(round(concentration * 100, 2)) + "% of portfolio (limit: 10%)",
                    "value": round(concentration * 100, 2),
                    "action": "BLOCK_TRADE"
                }
                violations.append(violation)
                print("  VIOLATION: " + acct + " - " + violation["detail"])


def check_sector_concentration(positions, clients):
    """RULE-002: Sector concentration limit (30%)"""
    global violations
    print("\nChecking RULE-002: Sector Concentration...")

    for acct in positions:
        total_value = sum([p["market_value"] for p in positions[acct]])
        if total_value == 0:
            continue

        # aggregate by sector
        sector_values = {}
        for pos in positions[acct]:
            sector = pos["sector"]
            if sector not in sector_values:
                sector_values[sector] = 0.0
            sector_values[sector] = sector_values[sector] + pos["market_value"]

        for sector, value in sector_values.items():
            concentration = value / total_value
            if concentration > 0.30:
                violation = {
                    "rule_id": "RULE-002",
                    "severity": "HIGH",
                    "account": acct,
                    "client": clients.get(acct, {}).get("name", "UNKNOWN"),
                    "detail": sector + " sector is " + str(round(concentration * 100, 2)) + "% of portfolio (limit: 30%)",
                    "value": round(concentration * 100, 2),
                    "action": "ALERT"
                }
                violations.append(violation)
                print("  VIOLATION: " + acct + " - " + violation["detail"])


def check_fi_minimum(positions, clients):
    """RULE-003: Fixed income minimum for retirement/pension accounts"""
    global violations
    print("\nChecking RULE-003: Fixed Income Minimum...")

    for acct in positions:
        client_type = clients.get(acct, {}).get("type", "")
        if client_type not in ["401K", "PENSION"]:
            continue

        total_value = sum([p["market_value"] for p in positions[acct]])
        fi_value = sum([p["market_value"] for p in positions[acct] if p["asset_class"] == "FIXED_INCOME"])

        if total_value == 0:
            continue

        fi_pct = fi_value / total_value
        if fi_pct < 0.15:
            violation = {
                "rule_id": "RULE-003",
                "severity": "MEDIUM",
                "account": acct,
                "client": clients.get(acct, {}).get("name", "UNKNOWN"),
                "detail": "Fixed income is " + str(round(fi_pct * 100, 2)) + "% (minimum: 15% for " + client_type + " accounts)",
                "value": round(fi_pct * 100, 2),
                "action": "ALERT"
            }
            violations.append(violation)
            print("  VIOLATION: " + acct + " - " + violation["detail"])


def write_compliance_report(date_str):
    """write compliance report"""
    etl_config.ensure_dirs()
    output_path = str(OUTPUT_DIR / ("compliance_report_" + date_str + ".csv"))

    print("\nWriting compliance report to: " + output_path)

    f = open(output_path, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(["RULE_ID", "SEVERITY", "ACCOUNT", "CLIENT", "DETAIL",
                      "VALUE", "ACTION", "AS_OF_DATE", "GENERATED_AT"])

    for v in violations:
        writer.writerow([
            v["rule_id"], v["severity"], v["account"], v["client"],
            v["detail"], v["value"], v["action"], date_str,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])

    f.close()

    # print summary
    critical_count = len([v for v in violations if v["severity"] == "CRITICAL"])
    high_count = len([v for v in violations if v["severity"] == "HIGH"])
    medium_count = len([v for v in violations if v["severity"] == "MEDIUM"])

    print("\n" + "=" * 60)
    print("COMPLIANCE SUMMARY")
    print("=" * 60)
    print("  CRITICAL: " + str(critical_count))
    print("  HIGH:     " + str(high_count))
    print("  MEDIUM:   " + str(medium_count))
    print("  TOTAL:    " + str(len(violations)))

    if critical_count > 0:
        print("\n  *** CRITICAL VIOLATIONS FOUND - TRADING MAY BE RESTRICTED ***")

    print("=" * 60)


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("MERIDIAN CAPITAL - COMPLIANCE CHECK")
    print("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if len(sys.argv) > 1:
        run_date = sys.argv[1]
    else:
        run_date = "20240315"

    # Load rules and data
    load_rules()
    positions, clients = load_positions_and_clients(run_date)

    # Run checks
    check_concentration_limits(positions, clients)
    check_sector_concentration(positions, clients)
    check_fi_minimum(positions, clients)

    # Write report
    write_compliance_report(run_date)

    if len(violations) > 0:
        print("\nCOMPLIANCE CHECK: VIOLATIONS FOUND")
        sys.exit(1)
    else:
        print("\nCOMPLIANCE CHECK: ALL CLEAR")
        sys.exit(0)
