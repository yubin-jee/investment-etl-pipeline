#!/usr/bin/env python
"""
Client Report Generator - Meridian Capital Partners
Generates monthly performance reports for each client account.

Author: Mike Torres
NOTE: This generates a text report. The ops team then manually
      copies this into an Excel template and emails it to clients.
      Yes, we know this is terrible. No budget to fix it.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logging_config import get_logger

log = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"

# benchmark returns (hardcoded monthly - updated manually by PM team)
BENCHMARK_RETURNS = {
    "SP500": {"2024-01": 1.59, "2024-02": 5.17, "2024-03": 3.10},
    "RUSSELL2000": {"2024-01": -3.89, "2024-02": 5.52, "2024-03": 3.39},
    "6040BLEND": {"2024-01": 0.85, "2024-02": 3.21, "2024-03": 2.15},
    "MSCI_WORLD": {"2024-01": 1.15, "2024-02": 4.28, "2024-03": 3.05},
    "CUSTOM_BLEND": {"2024-01": 0.95, "2024-02": 4.10, "2024-03": 2.85},
    "LBAG_BLEND": {"2024-01": 0.45, "2024-02": 2.80, "2024-03": 1.75},
}


@dataclass
class Account:
    account: str
    client_name: str
    market_value: float
    cost_basis: float
    unrealized_pnl: float
    return_pct: float
    positions: int
    equity_value: float
    fi_value: float
    equity_pct: float
    fi_pct: float
    daily_fee: float
    pm: str
    benchmark: str


def load_nav_data(date_str: str) -> list[Account]:
    """Load NAV report data."""
    nav_file = REPORTS_DIR / f"nav_report_{date_str}.csv"

    if not nav_file.exists():
        log.info(f"ERROR: NAV report not found: {nav_file}")
        log.info("Please run calc_nav.py first")
        sys.exit(1)

    accounts: list[Account] = []
    with open(nav_file) as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            accounts.append(
                Account(
                    account=row[0],
                    client_name=row[1],
                    market_value=float(row[2]),
                    cost_basis=float(row[3]),
                    unrealized_pnl=float(row[4]),
                    return_pct=float(row[5]),
                    positions=int(row[6]),
                    equity_value=float(row[7]),
                    fi_value=float(row[8]),
                    equity_pct=float(row[9]),
                    fi_pct=float(row[10]),
                    daily_fee=float(row[11]),
                    pm=row[12],
                    benchmark=row[13],
                )
            )

    return accounts


def generate_report(account: Account, date_str: str) -> str:
    """Generate text report for a single account."""
    report: list[str] = []
    report.append("=" * 70)
    report.append("  MERIDIAN CAPITAL PARTNERS")
    report.append("  Investment Performance Report")
    report.append("  " + "-" * 40)
    report.append(f"  Client:    {account.client_name}")
    report.append(f"  Account:   {account.account}")
    report.append(f"  PM:        {account.pm}")
    report.append(f"  As Of:     {date_str[:4]}-{date_str[4:6]}-{date_str[6:]}")
    report.append("  Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    report.append("=" * 70)
    report.append("")

    # Portfolio Summary
    report.append("  PORTFOLIO SUMMARY")
    report.append("  " + "-" * 40)
    report.append(f"  Total Market Value:     ${account.market_value:>15,.2f}")
    report.append(f"  Total Cost Basis:       ${account.cost_basis:>15,.2f}")
    report.append(f"  Unrealized Gain/Loss:   ${account.unrealized_pnl:>15,.2f}")
    report.append(f"  Total Return:           {account.return_pct:>15.2f}%")
    report.append(f"  Number of Positions:    {account.positions:>15d}")
    report.append("")

    # Asset Allocation
    report.append("  ASSET ALLOCATION")
    report.append("  " + "-" * 40)
    report.append(
        f"  Equities:               {account.equity_pct:>6.1f}%  ${account.equity_value:>12,.2f}"
    )
    report.append(f"  Fixed Income:           {account.fi_pct:>6.1f}%  ${account.fi_value:>12,.2f}")
    cash_pct = 100.0 - account.equity_pct - account.fi_pct
    cash_val = account.market_value - account.equity_value - account.fi_value
    report.append(f"  Cash & Equivalents:     {cash_pct:>6.1f}%  ${cash_val:>12,.2f}")
    report.append("")

    # Performance vs Benchmark
    benchmark = account.benchmark
    report.append(f"  PERFORMANCE vs BENCHMARK ({benchmark})")
    report.append("  " + "-" * 40)
    if benchmark in BENCHMARK_RETURNS:
        bm_returns = BENCHMARK_RETURNS[benchmark]
        report.append("  Month       Portfolio    Benchmark    Excess")
        report.append("  " + "-" * 50)
        for month, bm_ret in sorted(bm_returns.items()):
            # we don't actually have monthly returns calculated
            # so just use the total return divided by 3 as an approximation
            # TODO: fix this when we have actual monthly data
            portfolio_ret = account.return_pct / 3
            excess = portfolio_ret - bm_ret
            report.append(f"  {month:12s}{portfolio_ret:>10.2f}%{bm_ret:>12.2f}%{excess:>10.2f}%")
    else:
        report.append("  Benchmark data not available")
    report.append("")

    # Fee Information
    report.append("  FEE INFORMATION")
    report.append("  " + "-" * 40)
    annual_fee = account.daily_fee * 365
    report.append(f"  Daily Fee Accrual:      ${account.daily_fee:>15,.2f}")
    report.append(f"  Estimated Annual Fee:   ${annual_fee:>15,.2f}")
    report.append("")

    # Disclaimer
    report.append("  " + "-" * 60)
    report.append("  IMPORTANT: This report is for informational purposes only.")
    report.append("  Past performance does not guarantee future results.")
    report.append("  Please contact your portfolio manager with any questions.")
    report.append("  " + "-" * 60)
    report.append("")

    return "\n".join(report)


def write_reports(accounts: list[Account], date_str: str) -> None:
    """Write individual client reports."""
    output_dir = REPORTS_DIR / "client_reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    for account in accounts:
        report_text = generate_report(account, date_str)

        filename = f"report_{account.account}_{date_str}.txt"
        filepath = output_dir / filename

        filepath.write_text(report_text)

        log.info(f"  Generated: {filename}")


def main(argv: list[str]) -> None:
    log.info("=" * 60)
    log.info("MERIDIAN CAPITAL - CLIENT REPORT GENERATION")
    log.info("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    run_date = argv[1] if len(argv) > 1 else "20240315"

    # Load NAV data (must run calc_nav.py first)
    accounts = load_nav_data(run_date)
    log.info(f"Loaded {len(accounts)} accounts")

    # Generate reports
    log.info("\nGenerating client reports...")
    write_reports(accounts, run_date)

    log.info("\nREPORT GENERATION COMPLETE")
    log.info("Reports written to: reports/client_reports/")


if __name__ == "__main__":
    main(sys.argv)
