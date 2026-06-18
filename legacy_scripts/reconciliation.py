#!/usr/bin/env python
"""
Position Reconciliation Script - Meridian Capital Partners
Compares internal positions with custodian (State Street) positions.

Author: Mike Torres
NOTE: Custodian file format changed in 2023 and this script was patched
      by Dave in ops. The parsing is fragile - do not change column positions.
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

# Legacy Windows network drive locations (kept for display; the local fallbacks
# below are used off Windows).
HOLDINGS_DIR = r"C:\MeridianData\holdings"
OUTPUT_DIR = r"C:\MeridianData\reports"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "legacy_data"
REPORTS_DIR = BASE_DIR / "reports"

# tolerance for matching (in dollars)
TOLERANCE = 1.00  # $1 tolerance - Sandra requested this after too many false breaks

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


@dataclass
class Position:
    account: str
    ticker: str
    quantity: int
    market_value: float
    security_name: str = ""
    cusip: str = ""


@dataclass
class ReconResult:
    key: str
    status: str = ""
    detail: str = ""
    internal_qty: int = 0
    internal_val: float = 0.0
    custodian_qty: int = 0
    custodian_val: float = 0.0


def load_internal_positions(date_str: str) -> dict[str, Position]:
    """Load our internal position file."""
    file_path: str | Path = rf"{HOLDINGS_DIR}\portfolio_positions_{date_str}.csv"

    if not Path(file_path).exists():
        file_path = DATA_DIR / "holdings" / f"portfolio_positions_{date_str}.csv"

    log.info(f"Loading internal positions: {file_path}")

    internal_positions: dict[str, Position] = {}
    with open(file_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            acct = row[0]
            ticker = row[1]
            qty = int(row[4]) if row[4] else 0
            mkt_val = float(row[6]) if row[6] else 0.0

            if qty == 0:
                continue

            key = f"{acct}|{ticker}"
            internal_positions[key] = Position(
                account=acct,
                ticker=ticker,
                quantity=qty,
                market_value=mkt_val,
            )

    log.info(f"Loaded {len(internal_positions)} internal positions")
    return internal_positions


def load_custodian_positions(date_str: str) -> dict[str, Position]:
    """Parse the State Street custodian report.

    This is a fixed-width text file with headers and footers.
    Format is fragile - hardcoded column positions.
    """
    file_path: str | Path = rf"{HOLDINGS_DIR}\custodian_positions_{date_str}.txt"

    if not Path(file_path).exists():
        file_path = DATA_DIR / "holdings" / f"custodian_positions_{date_str}.txt"

    log.info(f"Loading custodian positions: {file_path}")

    custodian_positions: dict[str, Position] = {}
    lines = Path(file_path).read_text().splitlines(keepends=True)

    for line in lines:
        # skip headers, footers, separator lines
        if line.startswith("=") or line.startswith(" ") or line.startswith("-"):
            continue
        if any(token in line for token in ("ACCOUNT", "TOTAL", "GENERATED", "CLIENT", "AS OF")):
            continue
        if len(line.strip()) < 10:
            continue

        # parse fixed-width columns
        # ACCOUNT(0-10) SECURITY(11-31) CUSIP(32-45) QTY(46-56) MKT_PRICE(57-69) MKT_VALUE(70-85)
        try:
            acct = line[0:10].strip()
            security_name = line[11:31].strip()
            cusip = line[32:45].strip()
            qty_str = line[46:56].strip().replace(",", "")
            mkt_val_str = line[70:85].strip().replace(",", "")

            if not acct or not qty_str:
                continue

            qty = int(qty_str)
            mkt_val = float(mkt_val_str)

            # we need ticker but custodian only gives security name and cusip
            # this is a manual mapping - TERRIBLE but it works
            ticker = cusip_to_ticker(cusip, security_name)

            if ticker:
                key = f"{acct}|{ticker}"
                custodian_positions[key] = Position(
                    account=acct,
                    ticker=ticker,
                    quantity=qty,
                    market_value=mkt_val,
                    security_name=security_name,
                    cusip=cusip,
                )
        except (ValueError, IndexError) as e:
            log.info(f"ERROR parsing custodian line: {line.strip()}")
            log.info(f"  {e}")

    log.info(f"Loaded {len(custodian_positions)} custodian positions")
    return custodian_positions


def cusip_to_ticker(cusip: str, security_name: str) -> str | None:
    """Manual CUSIP to ticker mapping.

    TODO: hook this up to the reference data service.
    For now just hardcoding the ones we have.
    """
    if cusip in CUSIP_MAP:
        return CUSIP_MAP[cusip]

    # try to guess from security name (this is bad)
    name = security_name.upper()
    if "VANGUARD" in name and "BOND" in name:
        return "BND"
    if "ISHARES" in name and "AGG" in name:
        return "AGG"
    if "ISHARES" in name and "TREAS" in name:
        return "TLT"

    log.info(f"WARNING: Unknown CUSIP {cusip} for {security_name}")
    return None


def run_reconciliation(
    internal_positions: dict[str, Position],
    custodian_positions: dict[str, Position],
) -> tuple[list[ReconResult], bool]:
    """Compare internal vs custodian positions."""
    log.info("\n" + "=" * 60)
    log.info("RUNNING RECONCILIATION")
    log.info("=" * 60)

    all_keys = set(internal_positions) | set(custodian_positions)

    recon_results: list[ReconResult] = []
    matched = 0
    breaks = 0
    internal_only = 0
    custodian_only = 0

    for key in sorted(all_keys):
        internal = internal_positions.get(key)
        custodian = custodian_positions.get(key)

        result = ReconResult(key=key)

        if internal and custodian:
            # both sides exist - compare
            qty_match = internal.quantity == custodian.quantity
            val_diff = abs(internal.market_value - custodian.market_value)
            val_match = val_diff <= TOLERANCE

            if qty_match and val_match:
                result.status = "MATCHED"
                result.detail = ""
                matched += 1
            else:
                result.status = "BREAK"
                details = []
                if not qty_match:
                    details.append(
                        f"QTY: Internal={internal.quantity} Custodian={custodian.quantity}"
                    )
                if not val_match:
                    details.append(
                        f"VAL: Internal={internal.market_value} "
                        f"Custodian={custodian.market_value} Diff={round(val_diff, 2)}"
                    )
                result.detail = "; ".join(details)
                breaks += 1
                log.info(f"  BREAK: {key} - {result.detail}")

            result.internal_qty = internal.quantity
            result.internal_val = internal.market_value
            result.custodian_qty = custodian.quantity
            result.custodian_val = custodian.market_value

        elif internal and not custodian:
            result.status = "INTERNAL_ONLY"
            result.detail = "Position exists internally but not at custodian"
            result.internal_qty = internal.quantity
            result.internal_val = internal.market_value
            result.custodian_qty = 0
            result.custodian_val = 0.0
            internal_only += 1
            log.info(f"  INTERNAL ONLY: {key}")

        elif custodian and not internal:
            result.status = "CUSTODIAN_ONLY"
            result.detail = "Position exists at custodian but not internally"
            result.internal_qty = 0
            result.internal_val = 0.0
            result.custodian_qty = custodian.quantity
            result.custodian_val = custodian.market_value
            custodian_only += 1
            log.info(f"  CUSTODIAN ONLY: {key}")

        recon_results.append(result)

    log.info("\n  SUMMARY:")
    log.info(f"  Matched:        {matched}")
    log.info(f"  Breaks:         {breaks}")
    log.info(f"  Internal Only:  {internal_only}")
    log.info(f"  Custodian Only: {custodian_only}")

    clean = breaks == 0 and internal_only == 0 and custodian_only == 0
    return recon_results, clean


def write_recon_report(recon_results: list[ReconResult], date_str: str) -> None:
    """Write reconciliation report."""
    output_path: str | Path = rf"{OUTPUT_DIR}\recon_report_{date_str}.csv"

    if not Path(OUTPUT_DIR).exists():
        output_path = REPORTS_DIR / f"recon_report_{date_str}.csv"

    log.info(f"\nWriting recon report to: {output_path}")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "KEY",
                "STATUS",
                "INTERNAL_QTY",
                "INTERNAL_VALUE",
                "CUSTODIAN_QTY",
                "CUSTODIAN_VALUE",
                "DETAIL",
                "AS_OF_DATE",
                "GENERATED_AT",
            ]
        )

        for r in recon_results:
            writer.writerow(
                [
                    r.key,
                    r.status,
                    r.internal_qty,
                    r.internal_val,
                    r.custodian_qty,
                    r.custodian_val,
                    r.detail,
                    date_str,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )


def main(argv: list[str]) -> int:
    log.info("=" * 60)
    log.info("MERIDIAN CAPITAL - POSITION RECONCILIATION")
    log.info("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    run_date = argv[1] if len(argv) > 1 else "20240315"
    if not re.fullmatch(r"\d{8}", run_date):
        raise SystemExit(f"Invalid run date {run_date!r}: expected YYYYMMDD")

    internal_positions = load_internal_positions(run_date)
    custodian_positions = load_custodian_positions(run_date)

    recon_results, clean = run_reconciliation(internal_positions, custodian_positions)

    write_recon_report(recon_results, run_date)

    if clean:
        log.info("\nRECONCILIATION: CLEAN")
        return 0

    log.info("\nRECONCILIATION: BREAKS FOUND - MANUAL REVIEW REQUIRED")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
