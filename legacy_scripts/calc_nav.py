#!/usr/bin/env python
"""
NAV Calculation Script - Meridian Capital Partners
Calculates Net Asset Value for all client accounts

Original Author: Lisa Park (moved to compliance dept 2022)
Dependencies: needs market_prices file to exist in pricing folder
              needs portfolio_positions file in holdings folder
              needs client_master.csv in clients folder

WARNING: This script has known rounding issues with large positions.
         Sandra in accounting manually adjusts the NAV report each morning.

Last Modified: 2021-11-03
"""

import csv
import os
import sys
from datetime import datetime

import etl_config

# OS-agnostic, configurable paths (see etl_config / batch_config.ini / .env)
PRICING_DIR = etl_config.PRICING_DIR
HOLDINGS_DIR = etl_config.HOLDINGS_DIR
CLIENTS_DIR = etl_config.CLIENTS_DIR
OUTPUT_DIR = etl_config.REPORT_DIR

# fee schedules - hardcoded because the database is too slow
FEE_SCHEDULES = {
    "TIER_1": 0.0100,  # 1.00% annual
    "TIER_2": 0.0150,  # 1.50% annual
    "TIER_3": 0.0085,  # 0.85% annual
}

prices = {}
positions = {}
clients = {}
nav_results = []


def load_prices(date_str):
    """load market prices for given date"""
    global prices
    file_path = str(PRICING_DIR / ("market_prices_" + date_str + ".csv"))

    print("Loading prices from: " + file_path)

    f = open(file_path, "r")
    reader = csv.reader(f)
    header = next(reader)  # skip header

    for row in reader:
        ticker = row[0]
        close_price = float(row[5])  # CLOSE column
        prices[ticker] = close_price

    f.close()
    print("Loaded " + str(len(prices)) + " prices")


def load_positions(date_str):
    """load portfolio positions"""
    global positions
    file_path = str(HOLDINGS_DIR / ("portfolio_positions_" + date_str + ".csv"))

    print("Loading positions from: " + file_path)

    f = open(file_path, "r")
    reader = csv.reader(f)
    header = next(reader)

    for row in reader:
        acct = row[0]
        ticker = row[1]
        qty = int(row[4]) if row[4] else 0
        avg_cost = float(row[5]) if row[5] else 0.0

        if acct not in positions:
            positions[acct] = []

        positions[acct].append({
            "ticker": ticker,
            "quantity": qty,
            "avg_cost": avg_cost,
            "asset_class": row[8],
            "sector": row[9]
        })

    f.close()
    print("Loaded positions for " + str(len(positions)) + " accounts")


def load_clients():
    """load client master data"""
    global clients
    file_path = str(CLIENTS_DIR / "client_master.csv")

    print("Loading clients from: " + file_path)

    f = open(file_path, "r")
    reader = csv.reader(f)
    header = next(reader)

    for row in reader:
        acct = row[0]
        clients[acct] = {
            "name": row[1],
            "type": row[2],
            "fee_schedule": row[5],
            "benchmark": row[7],
            "pm": row[8],
            "status": row[9]
        }

    f.close()
    print("Loaded " + str(len(clients)) + " clients")


def calculate_nav():
    """calculate NAV for each account"""
    global nav_results
    print("\n" + "=" * 60)
    print("CALCULATING NAV")
    print("=" * 60)

    for acct in positions:
        total_market_value = 0.0
        total_cost_basis = 0.0
        position_count = 0
        equity_value = 0.0
        fi_value = 0.0

        for pos in positions[acct]:
            if pos["quantity"] == 0:
                continue

            ticker = pos["ticker"]
            qty = pos["quantity"]
            cost = pos["avg_cost"]

            # get current price
            if ticker in prices:
                current_price = prices[ticker]
            else:
                # no price found - use avg cost as fallback
                # TODO: this is wrong, should error out
                print("WARNING: No price for " + ticker + " in account " + acct + ", using avg cost")
                current_price = cost

            mkt_val = qty * current_price
            cost_val = qty * cost
            unrealized_pnl = mkt_val - cost_val

            total_market_value = total_market_value + mkt_val
            total_cost_basis = total_cost_basis + cost_val
            position_count = position_count + 1

            if pos["asset_class"] == "EQUITY":
                equity_value = equity_value + mkt_val
            elif pos["asset_class"] == "FIXED_INCOME":
                fi_value = fi_value + mkt_val

        # calculate fee accrual
        if acct in clients:
            fee_tier = clients[acct]["fee_schedule"]
            annual_fee_rate = FEE_SCHEDULES.get(fee_tier, 0.01)
            # daily fee accrual = annual rate / 365
            daily_fee = total_market_value * annual_fee_rate / 365
        else:
            daily_fee = 0.0
            print("WARNING: No client record for " + acct)

        # asset allocation percentages
        if total_market_value > 0:
            equity_pct = equity_value / total_market_value * 100
            fi_pct = fi_value / total_market_value * 100
        else:
            equity_pct = 0.0
            fi_pct = 0.0

        nav_result = {
            "account": acct,
            "client_name": clients.get(acct, {}).get("name", "UNKNOWN"),
            "total_market_value": round(total_market_value, 2),
            "total_cost_basis": round(total_cost_basis, 2),
            "total_unrealized_pnl": round(total_market_value - total_cost_basis, 2),
            "return_pct": round((total_market_value - total_cost_basis) / total_cost_basis * 100, 2) if total_cost_basis > 0 else 0,
            "position_count": position_count,
            "equity_value": round(equity_value, 2),
            "fi_value": round(fi_value, 2),
            "equity_pct": round(equity_pct, 2),
            "fi_pct": round(fi_pct, 2),
            "daily_fee_accrual": round(daily_fee, 2),
            "pm": clients.get(acct, {}).get("pm", "UNKNOWN"),
            "benchmark": clients.get(acct, {}).get("benchmark", "UNKNOWN")
        }

        nav_results.append(nav_result)

        # print summary
        print("\n  " + acct + " - " + nav_result["client_name"])
        print("    Market Value:     ${:>15,.2f}".format(total_market_value))
        print("    Cost Basis:       ${:>15,.2f}".format(total_cost_basis))
        print("    Unrealized P&L:   ${:>15,.2f}".format(total_market_value - total_cost_basis))
        print("    Return:           {:>15.2f}%".format(nav_result["return_pct"]))
        print("    Equity/FI Split:  {:>6.1f}% / {:.1f}%".format(equity_pct, fi_pct))
        print("    Daily Fee:        ${:>15,.2f}".format(daily_fee))


def write_nav_report(date_str):
    """write NAV report to CSV"""
    etl_config.ensure_dirs()
    output_path = str(OUTPUT_DIR / ("nav_report_" + date_str + ".csv"))

    print("\nWriting NAV report to: " + output_path)

    f = open(output_path, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(["ACCOUNT", "CLIENT_NAME", "TOTAL_MKT_VALUE", "COST_BASIS",
                      "UNREALIZED_PNL", "RETURN_PCT", "POSITIONS", "EQUITY_VALUE",
                      "FI_VALUE", "EQUITY_PCT", "FI_PCT", "DAILY_FEE",
                      "PM", "BENCHMARK", "AS_OF_DATE", "GENERATED_AT"])

    total_aum = 0
    for nav in nav_results:
        writer.writerow([
            nav["account"], nav["client_name"], nav["total_market_value"],
            nav["total_cost_basis"], nav["total_unrealized_pnl"], nav["return_pct"],
            nav["position_count"], nav["equity_value"], nav["fi_value"],
            nav["equity_pct"], nav["fi_pct"], nav["daily_fee_accrual"],
            nav["pm"], nav["benchmark"], date_str,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        total_aum = total_aum + nav["total_market_value"]

    f.close()

    print("\n" + "=" * 60)
    print("FIRM-WIDE AUM: ${:,.2f}".format(total_aum))
    print("Total Accounts: " + str(len(nav_results)))
    print("=" * 60)


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print("=" * 60)
    print("MERIDIAN CAPITAL - NAV CALCULATION")
    print("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if len(sys.argv) > 1:
        run_date = sys.argv[1]
    else:
        run_date = "20240315"

    # Step 1: Load data
    load_prices(run_date)
    load_positions(run_date)
    load_clients()

    # Step 2: Calculate NAV
    calculate_nav()

    # Step 3: Write report
    write_nav_report(run_date)

    print("\nNAV CALCULATION COMPLETE")
