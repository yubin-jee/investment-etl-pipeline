#!/usr/bin/env python
"""
Client Report Generator - Meridian Capital Partners
Generates monthly performance reports for each client account

Author: Mike Torres
NOTE: This generates a text report. The ops team then manually
      copies this into an Excel template and emails it to clients.
      Yes, we know this is terrible. No budget to fix it.

Last Modified: 2022-04-22
"""

import csv
import os
import sys
from datetime import datetime

# paths
REPORTS_DIR = "C:\\MeridianData\\reports\\"

# benchmark returns (hardcoded monthly - updated manually by PM team)
BENCHMARK_RETURNS = {
    "SP500": {"2024-01": 1.59, "2024-02": 5.17, "2024-03": 3.10},
    "RUSSELL2000": {"2024-01": -3.89, "2024-02": 5.52, "2024-03": 3.39},
    "6040BLEND": {"2024-01": 0.85, "2024-02": 3.21, "2024-03": 2.15},
    "MSCI_WORLD": {"2024-01": 1.15, "2024-02": 4.28, "2024-03": 3.05},
    "CUSTOM_BLEND": {"2024-01": 0.95, "2024-02": 4.10, "2024-03": 2.85},
    "LBAG_BLEND": {"2024-01": 0.45, "2024-02": 2.80, "2024-03": 1.75},
}


def load_nav_data(date_str):
    """load NAV report data"""
    nav_file = os.path.join(os.path.dirname(__file__), "..", "reports", "nav_report_" + date_str + ".csv")

    if not os.path.exists(nav_file):
        print("ERROR: NAV report not found: " + nav_file)
        print("Please run calc_nav.py first")
        sys.exit(1)

    accounts = []
    f = open(nav_file, "r")
    reader = csv.reader(f)
    header = next(reader)

    for row in reader:
        accounts.append({
            "account": row[0],
            "client_name": row[1],
            "market_value": float(row[2]),
            "cost_basis": float(row[3]),
            "unrealized_pnl": float(row[4]),
            "return_pct": float(row[5]),
            "positions": int(row[6]),
            "equity_value": float(row[7]),
            "fi_value": float(row[8]),
            "equity_pct": float(row[9]),
            "fi_pct": float(row[10]),
            "daily_fee": float(row[11]),
            "pm": row[12],
            "benchmark": row[13]
        })

    f.close()
    return accounts


def generate_report(account, date_str):
    """generate text report for a single account"""
    report = []
    report.append("=" * 70)
    report.append("  MERIDIAN CAPITAL PARTNERS")
    report.append("  Investment Performance Report")
    report.append("  " + "-" * 40)
    report.append("  Client:    " + account["client_name"])
    report.append("  Account:   " + account["account"])
    report.append("  PM:        " + account["pm"])
    report.append("  As Of:     " + date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:])
    report.append("  Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    report.append("=" * 70)
    report.append("")

    # Portfolio Summary
    report.append("  PORTFOLIO SUMMARY")
    report.append("  " + "-" * 40)
    report.append("  Total Market Value:     ${:>15,.2f}".format(account["market_value"]))
    report.append("  Total Cost Basis:       ${:>15,.2f}".format(account["cost_basis"]))
    report.append("  Unrealized Gain/Loss:   ${:>15,.2f}".format(account["unrealized_pnl"]))
    report.append("  Total Return:           {:>15.2f}%".format(account["return_pct"]))
    report.append("  Number of Positions:    {:>15d}".format(account["positions"]))
    report.append("")

    # Asset Allocation
    report.append("  ASSET ALLOCATION")
    report.append("  " + "-" * 40)
    report.append("  Equities:               {:>6.1f}%  ${:>12,.2f}".format(
        account["equity_pct"], account["equity_value"]))
    report.append("  Fixed Income:           {:>6.1f}%  ${:>12,.2f}".format(
        account["fi_pct"], account["fi_value"]))
    cash_pct = 100.0 - account["equity_pct"] - account["fi_pct"]
    cash_val = account["market_value"] - account["equity_value"] - account["fi_value"]
    report.append("  Cash & Equivalents:     {:>6.1f}%  ${:>12,.2f}".format(cash_pct, cash_val))
    report.append("")

    # Performance vs Benchmark
    benchmark = account["benchmark"]
    report.append("  PERFORMANCE vs BENCHMARK (" + benchmark + ")")
    report.append("  " + "-" * 40)
    if benchmark in BENCHMARK_RETURNS:
        bm_returns = BENCHMARK_RETURNS[benchmark]
        report.append("  Month       Portfolio    Benchmark    Excess")
        report.append("  " + "-" * 50)
        for month, bm_ret in sorted(bm_returns.items()):
            # we don't actually have monthly returns calculated
            # so just use the total return divided by 3 as an approximation
            # TODO: fix this when we have actual monthly data
            portfolio_ret = account["return_pct"] / 3
            excess = portfolio_ret - bm_ret
            report.append("  {:12s}{:>10.2f}%{:>12.2f}%{:>10.2f}%".format(
                month, portfolio_ret, bm_ret, excess))
    else:
        report.append("  Benchmark data not available")
    report.append("")

    # Fee Information
    report.append("  FEE INFORMATION")
    report.append("  " + "-" * 40)
    annual_fee = account["daily_fee"] * 365
    report.append("  Daily Fee Accrual:      ${:>15,.2f}".format(account["daily_fee"]))
    report.append("  Estimated Annual Fee:   ${:>15,.2f}".format(annual_fee))
    report.append("")

    # Disclaimer
    report.append("  " + "-" * 60)
    report.append("  IMPORTANT: This report is for informational purposes only.")
    report.append("  Past performance does not guarantee future results.")
    report.append("  Please contact your portfolio manager with any questions.")
    report.append("  " + "-" * 60)
    report.append("")

    return "\n".join(report)


def write_reports(accounts, date_str):
    """write individual client reports"""
    output_dir = os.path.join(os.path.dirname(__file__), "..", "reports", "client_reports")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for account in accounts:
        report_text = generate_report(account, date_str)

        filename = "report_" + account["account"] + "_" + date_str + ".txt"
        filepath = os.path.join(output_dir, filename)

        f = open(filepath, "w")
        f.write(report_text)
        f.close()

        print("  Generated: " + filename)


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("MERIDIAN CAPITAL - CLIENT REPORT GENERATION")
    print("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if len(sys.argv) > 1:
        run_date = sys.argv[1]
    else:
        run_date = "20240315"

    # Load NAV data (must run calc_nav.py first)
    accounts = load_nav_data(run_date)
    print("Loaded " + str(len(accounts)) + " accounts")

    # Generate reports
    print("\nGenerating client reports...")
    write_reports(accounts, run_date)

    print("\nREPORT GENERATION COMPLETE")
    print("Reports written to: reports/client_reports/")
