#!/usr/bin/env python
"""
Trade Processing Script - Meridian Capital Partners
Original Author: Mike Torres (left company 2021)

Loads the daily trade CSV, validates it, computes gross/net amounts and
reconciles against fixed-width counterparty confirmation files.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logging_config import get_logger

log = get_logger(__name__)

# Legacy Windows network drive locations (kept for display; never resolve off
# Windows, so the local fallbacks below are used in practice).
TRADE_DIR = r"C:\MeridianData\trades"
OUTPUT_DIR = r"C:\MeridianData\processed"
ERROR_FILE = r"C:\MeridianData\logs\trade_errors.txt"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "legacy_data"
REPORTS_DIR = BASE_DIR / "reports"

VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


@dataclass
class Trade:
    trade_id: str
    account: str
    ticker: str
    side: str
    quantity: int
    price: float
    trade_date: str
    settle_date: str
    broker: str
    commission: float
    status: str
    gross_amount: float = 0.0
    net_amount: float = 0.0
    recon_status: str = ""


@dataclass
class Confirm:
    trade_id: str
    account: str
    ticker: str
    side: str
    quantity: int
    price: float
    currency: str
    trade_date: str
    status: str
    broker: str


def load_trades(file_path: str | Path) -> tuple[list[Trade], int]:
    """Load trades from a csv file. Returns the trades and the error count."""
    log.info(f"Loading trades from {file_path}...")

    trades: list[Trade] = []
    error_count = 0

    with open(file_path) as f:
        reader = csv.reader(f)
        next(reader)  # header

        for row in reader:
            try:
                trades.append(
                    Trade(
                        trade_id=row[0],
                        account=row[1],
                        ticker=row[2],
                        side=row[3],
                        quantity=int(row[4]),
                        price=float(row[5]),
                        trade_date=row[6],
                        settle_date=row[7],
                        broker=row[8],
                        commission=float(row[9]),
                        status=row[10],
                    )
                )
            except (ValueError, IndexError):
                log.info(f"ERROR processing row: {row}")
                error_count += 1

    log.info(f"Loaded {len(trades)} trades")
    return trades, error_count


def validate_trades(trades: list[Trade], error_count: int) -> tuple[list[Trade], int, int]:
    """Basic validation. Returns valid trades, error count and duplicate count."""
    log.info("Validating trades...")

    duplicate_count = 0
    processed_ids: list[str] = []
    valid_trades: list[Trade] = []

    for t in trades:
        # check for dupes
        if t.trade_id in processed_ids:
            log.info(f"DUPLICATE: {t.trade_id}")
            duplicate_count += 1
            continue

        # check broker
        if t.broker not in VALID_BROKERS:
            log.info(f"INVALID BROKER: {t.broker} for trade {t.trade_id}")
            error_count += 1
            continue

        # check quantity
        if t.quantity <= 0:
            log.info(f"INVALID QTY: {t.quantity} for trade {t.trade_id}")
            error_count += 1
            continue

        # check price
        if t.price <= 0:
            log.info(f"INVALID PRICE: {t.price} for trade {t.trade_id}")
            error_count += 1
            continue

        # check settle date exists
        if t.settle_date == "" or t.settle_date is None:
            log.info(f"WARNING: No settle date for {t.trade_id} - setting to T+2")
            # manually calculate T+2 - this is wrong for weekends but whatever
            parts = t.trade_date.split("/")
            month = int(parts[0])
            day = int(parts[1]) + 2
            year = int(parts[2])
            if day > 30:  # rough month end handling
                day = day - 30
                month = month + 1
            t.settle_date = f"{month:02d}/{day:02d}/{year}"

        processed_ids.append(t.trade_id)
        valid_trades.append(t)

    log.info(f"Valid trades: {len(valid_trades)}")
    log.info(f"Errors: {error_count}")
    log.info(f"Duplicates: {duplicate_count}")
    return valid_trades, error_count, duplicate_count


def calc_trade_amounts(trades: list[Trade]) -> None:
    """Calculate gross/net amounts for each trade."""
    log.info("Calculating trade amounts...")

    for t in trades:
        t.gross_amount = t.quantity * t.price
        t.net_amount = t.gross_amount + t.commission
        if t.side == "SELL":
            t.net_amount = t.gross_amount - t.commission

        # rounding - Mike said to round to 2 decimals
        t.gross_amount = round(t.gross_amount, 2)
        t.net_amount = round(t.net_amount, 2)


def write_output(trades: list[Trade], output_path: str | Path) -> None:
    """Write processed trades to output csv."""
    log.info(f"Writing output to {output_path}...")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "TRADE_ID",
                "ACCT_NUM",
                "TICKER",
                "SIDE",
                "QTY",
                "PRICE",
                "GROSS_AMT",
                "NET_AMT",
                "COMMISSION",
                "TRADE_DATE",
                "SETTLE_DATE",
                "BROKER",
                "STATUS",
                "PROCESSED_AT",
            ]
        )

        for t in trades:
            writer.writerow(
                [
                    t.trade_id,
                    t.account,
                    t.ticker,
                    t.side,
                    t.quantity,
                    t.price,
                    t.gross_amount,
                    t.net_amount,
                    t.commission,
                    t.trade_date,
                    t.settle_date,
                    t.broker,
                    t.status,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

    log.info(f"Wrote {len(trades)} trades to output")


def write_error_log(trades: list[Trade], error_count: int, duplicate_count: int) -> None:
    """Append errors to log file."""
    with open(ERROR_FILE, "a") as f:
        f.write("\n" + "=" * 50 + "\n")
        f.write("Trade Processing Run: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
        f.write(f"Errors: {error_count}\n")
        f.write(f"Duplicates: {duplicate_count}\n")
        f.write(f"Total Processed: {len(trades)}\n")


def process_counterparty_file(filepath: str | Path) -> list[Confirm]:
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
    log.info(f"Processing counterparty file: {filepath}")
    confirms: list[Confirm] = []
    current_broker = ""

    with open(filepath) as f:
        for line in f:
            if line.startswith("HDR"):
                # header record - extract broker name
                current_broker = line[14:36].strip()
                log.info(f"  Broker: {current_broker}")
            elif line.startswith("TRL"):
                # trailer record - skip
                count = int(line[3:12])
                log.info(f"  Trailer count: {count}")
            elif line.startswith("T-"):
                # trade record
                date_str = line[67:75]
                # price has implied 2 decimal places
                raw_price = int(line[52:64])
                confirms.append(
                    Confirm(
                        trade_id=line[0:16].strip(),
                        account=line[16:26].strip(),
                        ticker=line[26:36].strip(),
                        side=line[36:40].strip(),
                        quantity=int(line[40:52]),
                        price=raw_price / 100.0,
                        currency=line[64:67].strip(),
                        trade_date=f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}",
                        status=line[75:83].strip(),
                        broker=current_broker,
                    )
                )

    log.info(f"  Parsed {len(confirms)} confirms")
    return confirms


def reconcile_with_confirms(trades: list[Trade], confirms: list[Confirm]) -> None:
    """Match internal trades with counterparty confirms."""
    log.info("\nReconciling with counterparty confirms...")
    matched = 0
    breaks = 0

    for trade in trades:
        found = False
        for confirm in confirms:
            if trade.trade_id == confirm.trade_id:
                found = True
                # check price matches
                if abs(trade.price - confirm.price) > 0.01:
                    log.info(
                        f"PRICE BREAK: {trade.trade_id} "
                        f"Internal={trade.price} Confirm={confirm.price}"
                    )
                    breaks += 1
                    trade.recon_status = "PRICE_BREAK"
                # check quantity matches
                elif trade.quantity != confirm.quantity:
                    log.info(
                        f"QTY BREAK: {trade.trade_id} "
                        f"Internal={trade.quantity} Confirm={confirm.quantity}"
                    )
                    breaks += 1
                    trade.recon_status = "QTY_BREAK"
                else:
                    matched += 1
                    trade.recon_status = "MATCHED"
                break
        if not found:
            trade.recon_status = "UNMATCHED"

    log.info(f"Matched: {matched}")
    log.info(f"Breaks: {breaks}")


def main(argv: list[str]) -> None:
    log.info("=" * 50)
    log.info("MERIDIAN CAPITAL - DAILY TRADE PROCESSING")
    log.info("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 50)

    # get today's date for file name
    run_date = argv[1] if len(argv) > 1 else datetime.now().strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", run_date):
        raise SystemExit(f"Invalid run date {run_date!r}: expected YYYYMMDD")

    trade_file: str | Path = rf"{TRADE_DIR}\daily_trades_{run_date}.csv"
    confirm_file: str | Path = rf"{TRADE_DIR}\counterparty_confirms.dat"

    # check if files exist
    if not Path(trade_file).exists():
        log.info(f"ERROR: Trade file not found: {trade_file}")
        log.info("Trying fallback path...")
        trade_file = DATA_DIR / "trades" / f"daily_trades_{run_date}.csv"

    if not Path(confirm_file).exists():
        log.info(f"ERROR: Confirm file not found: {confirm_file}")
        confirm_file = DATA_DIR / "trades" / "counterparty_confirms.dat"

    # Step 1: Load trades
    trades, error_count = load_trades(trade_file)

    # Step 2: Validate
    trades, error_count, duplicate_count = validate_trades(trades, error_count)

    # Step 3: Calculate amounts
    calc_trade_amounts(trades)

    # Step 4: Process counterparty confirms
    if Path(confirm_file).exists():
        confirms = process_counterparty_file(confirm_file)
        reconcile_with_confirms(trades, confirms)
    else:
        log.info("WARNING: No counterparty file found, skipping reconciliation")

    # Step 5: Write output
    output_file = REPORTS_DIR / f"processed_trades_{run_date}.csv"
    write_output(trades, output_file)

    # Step 6: Log errors
    # write_error_log(...)  # commented out - log dir doesn't exist on new server

    log.info("\n" + "=" * 50)
    log.info("PROCESSING COMPLETE")
    log.info(f"Total Processed: {len(trades)}")
    log.info(f"Errors: {error_count}")
    log.info(f"Duplicates: {duplicate_count}")
    log.info("=" * 50)


if __name__ == "__main__":
    main(sys.argv)
