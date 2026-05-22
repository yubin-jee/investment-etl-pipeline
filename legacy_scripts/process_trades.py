#!/usr/bin/env python
"""
Trade Processing Script - Meridian Capital Partners
Original Author: Mike Torres (left company 2021)
Last Modified: 2022-08-14
NOTE: DO NOT MODIFY - this runs in production cron at 6:30 AM EST daily
"""

import csv
import os
import sys
import time
from datetime import datetime

# globals
TRADE_DIR = "C:\\MeridianData\\trades\\"  # mapped network drive
OUTPUT_DIR = "C:\\MeridianData\\processed\\"
ERROR_FILE = "C:\\MeridianData\\logs\\trade_errors.txt"
VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]

all_trades = []
error_count = 0
duplicate_count = 0
processed_ids = []


def load_trades(file_path):
    """load trades from csv file"""
    global all_trades, error_count
    print("Loading trades from " + file_path + "...")

    f = open(file_path, "r")
    reader = csv.reader(f)
    header = next(reader)

    for row in reader:
        try:
            trade = {}
            trade["trade_id"] = row[0]
            trade["account"] = row[1]
            trade["ticker"] = row[2]
            trade["side"] = row[3]
            trade["quantity"] = int(row[4])
            trade["price"] = float(row[5])
            trade["trade_date"] = row[6]
            trade["settle_date"] = row[7]
            trade["broker"] = row[8]
            trade["commission"] = float(row[9])
            trade["status"] = row[10]

            all_trades.append(trade)
        except Exception as e:
            print("ERROR processing row: " + str(row))
            error_count = error_count + 1

    f.close()
    print("Loaded " + str(len(all_trades)) + " trades")


def validate_trades():
    """basic validation - TODO: add more checks"""
    global all_trades, error_count, duplicate_count, processed_ids
    print("Validating trades...")

    valid_trades = []
    for t in all_trades:
        # check for dupes
        if t["trade_id"] in processed_ids:
            print("DUPLICATE: " + t["trade_id"])
            duplicate_count = duplicate_count + 1
            continue

        # check broker
        if t["broker"] not in VALID_BROKERS:
            print("INVALID BROKER: " + t["broker"] + " for trade " + t["trade_id"])
            error_count = error_count + 1
            continue

        # check quantity
        if t["quantity"] <= 0:
            print("INVALID QTY: " + str(t["quantity"]) + " for trade " + t["trade_id"])
            error_count = error_count + 1
            continue

        # check price
        if t["price"] <= 0:
            print("INVALID PRICE: " + str(t["price"]) + " for trade " + t["trade_id"])
            error_count = error_count + 1
            continue

        # check settle date exists
        if t["settle_date"] == "" or t["settle_date"] is None:
            print("WARNING: No settle date for " + t["trade_id"] + " - setting to T+2")
            # manually calculate T+2 - this is wrong for weekends but whatever
            parts = t["trade_date"].split("/")
            month = int(parts[0])
            day = int(parts[1]) + 2
            year = int(parts[2])
            if day > 30:  # rough month end handling
                day = day - 30
                month = month + 1
            t["settle_date"] = str(month).zfill(2) + "/" + str(day).zfill(2) + "/" + str(year)

        processed_ids.append(t["trade_id"])
        valid_trades.append(t)

    all_trades = valid_trades
    print("Valid trades: " + str(len(valid_trades)))
    print("Errors: " + str(error_count))
    print("Duplicates: " + str(duplicate_count))


def calc_trade_amounts():
    """calculate gross/net amounts for each trade"""
    global all_trades
    print("Calculating trade amounts...")

    for t in all_trades:
        t["gross_amount"] = t["quantity"] * t["price"]
        t["net_amount"] = t["gross_amount"] + t["commission"]
        if t["side"] == "SELL":
            t["net_amount"] = t["gross_amount"] - t["commission"]

        # rounding - Mike said to round to 2 decimals
        t["gross_amount"] = round(t["gross_amount"], 2)
        t["net_amount"] = round(t["net_amount"], 2)


def write_output(output_path):
    """write processed trades to output csv"""
    global all_trades
    print("Writing output to " + output_path + "...")

    f = open(output_path, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(["TRADE_ID", "ACCT_NUM", "TICKER", "SIDE", "QTY", "PRICE",
                      "GROSS_AMT", "NET_AMT", "COMMISSION", "TRADE_DATE",
                      "SETTLE_DATE", "BROKER", "STATUS", "PROCESSED_AT"])

    for t in all_trades:
        writer.writerow([
            t["trade_id"], t["account"], t["ticker"], t["side"],
            t["quantity"], t["price"], t["gross_amount"], t["net_amount"],
            t["commission"], t["trade_date"], t["settle_date"], t["broker"],
            t["status"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])

    f.close()
    print("Wrote " + str(len(all_trades)) + " trades to output")


def write_error_log():
    """append errors to log file"""
    global error_count, duplicate_count
    f = open(ERROR_FILE, "a")
    f.write("\n" + "=" * 50 + "\n")
    f.write("Trade Processing Run: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
    f.write("Errors: " + str(error_count) + "\n")
    f.write("Duplicates: " + str(duplicate_count) + "\n")
    f.write("Total Processed: " + str(len(all_trades)) + "\n")
    f.close()


def process_counterparty_file(filepath):
    """Parse fixed-width counterparty confirmation files
    Format: see spec doc (lost, ask Dave in ops)
    Field positions from memory:
      Trade ID: 0-16
      Account:  16-26
      Ticker:   26-36
      Side:     36-40
      Qty:      40-52 (zero padded)
      Price:    52-64 (implied 2 decimals)
      Currency: 64-67
      Date:     67-75 (MMDDYYYY)
      Status:   75-83
    """
    print("Processing counterparty file: " + filepath)
    confirms = []

    f = open(filepath, "r")
    current_broker = ""

    for line in f:
        if line.startswith("HDR"):
            # header record - extract broker name
            current_broker = line[11:31].strip()
            print("  Broker: " + current_broker)
        elif line.startswith("TRL"):
            # trailer record - skip
            count = int(line[3:11])
            print("  Trailer count: " + str(count))
        elif line.startswith("T-"):
            # trade record
            confirm = {}
            confirm["trade_id"] = line[0:14].strip()
            confirm["account"] = line[14:24].strip()
            confirm["ticker"] = line[24:34].strip()
            confirm["side"] = line[34:38].strip()
            confirm["quantity"] = int(line[38:46])
            # price has implied 2 decimal places
            raw_price = int(line[46:56])
            confirm["price"] = raw_price / 100.0
            confirm["currency"] = line[56:59].strip()
            date_str = line[59:67]
            confirm["trade_date"] = date_str[0:2] + "/" + date_str[2:4] + "/" + date_str[4:8]
            confirm["status"] = line[67:75].strip()
            confirm["broker"] = current_broker
            confirms.append(confirm)

    f.close()
    print("  Parsed " + str(len(confirms)) + " confirms")
    return confirms


def reconcile_with_confirms(confirms):
    """match internal trades with counterparty confirms"""
    global all_trades
    print("\nReconciling with counterparty confirms...")
    matched = 0
    breaks = 0

    for trade in all_trades:
        found = False
        for confirm in confirms:
            if trade["trade_id"] == confirm["trade_id"]:
                found = True
                # check price matches
                if abs(trade["price"] - confirm["price"]) > 0.01:
                    print("PRICE BREAK: " + trade["trade_id"] +
                          " Internal=" + str(trade["price"]) +
                          " Confirm=" + str(confirm["price"]))
                    breaks = breaks + 1
                    trade["recon_status"] = "PRICE_BREAK"
                # check quantity matches
                elif trade["quantity"] != confirm["quantity"]:
                    print("QTY BREAK: " + trade["trade_id"] +
                          " Internal=" + str(trade["quantity"]) +
                          " Confirm=" + str(confirm["quantity"]))
                    breaks = breaks + 1
                    trade["recon_status"] = "QTY_BREAK"
                else:
                    matched = matched + 1
                    trade["recon_status"] = "MATCHED"
                break
        if not found:
            trade["recon_status"] = "UNMATCHED"

    print("Matched: " + str(matched))
    print("Breaks: " + str(breaks))


# ============================================
# MAIN - daily trade processing
# ============================================
if __name__ == "__main__":
    print("=" * 50)
    print("MERIDIAN CAPITAL - DAILY TRADE PROCESSING")
    print("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # get today's date for file name
    if len(sys.argv) > 1:
        run_date = sys.argv[1]
    else:
        run_date = datetime.now().strftime("%Y%m%d")

    trade_file = TRADE_DIR + "daily_trades_" + run_date + ".csv"
    confirm_file = TRADE_DIR + "counterparty_confirms.dat"
    output_file = OUTPUT_DIR + "processed_trades_" + run_date + ".csv"

    # check if files exist
    if not os.path.exists(trade_file):
        print("ERROR: Trade file not found: " + trade_file)
        print("Trying fallback path...")
        trade_file = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "trades", "daily_trades_" + run_date + ".csv")

    if not os.path.exists(confirm_file):
        print("ERROR: Confirm file not found: " + confirm_file)
        confirm_file = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "trades", "counterparty_confirms.dat")

    # Step 1: Load trades
    load_trades(trade_file)

    # Step 2: Validate
    validate_trades()

    # Step 3: Calculate amounts
    calc_trade_amounts()

    # Step 4: Process counterparty confirms
    if os.path.exists(confirm_file):
        confirms = process_counterparty_file(confirm_file)
        reconcile_with_confirms(confirms)
    else:
        print("WARNING: No counterparty file found, skipping reconciliation")

    # Step 5: Write output
    output_file = os.path.join(os.path.dirname(__file__), "..", "reports", "processed_trades_" + run_date + ".csv")
    write_output(output_file)

    # Step 6: Log errors
    # write_error_log()  # commented out - log dir doesn't exist on new server

    print("\n" + "=" * 50)
    print("PROCESSING COMPLETE")
    print("Total Processed: " + str(len(all_trades)))
    print("Errors: " + str(error_count))
    print("Duplicates: " + str(duplicate_count))
    print("=" * 50)
