#!/usr/bin/env python
"""
NAV Calculation Script - Meridian Capital Partners
Calculates Net Asset Value for all client accounts.

Original Author: Lisa Park (moved to compliance dept 2022)
Dependencies: needs market_prices file to exist in pricing folder
              needs portfolio_positions file in holdings folder
              needs client_master.csv in clients folder

WARNING: This script has known rounding issues with large positions.
         Sandra in accounting manually adjusts the NAV report each morning.
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
PRICING_DIR = r"C:\MeridianData\pricing"
HOLDINGS_DIR = r"C:\MeridianData\holdings"
CLIENTS_DIR = r"C:\MeridianData\clients"
OUTPUT_DIR = r"C:\MeridianData\reports"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "legacy_data"
REPORTS_DIR = BASE_DIR / "reports"

# fee schedules - hardcoded because the database is too slow
FEE_SCHEDULES = {
    "TIER_1": 0.0100,  # 1.00% annual
    "TIER_2": 0.0150,  # 1.50% annual
    "TIER_3": 0.0085,  # 0.85% annual
}


@dataclass
class Position:
    ticker: str
    quantity: int
    avg_cost: float
    asset_class: str
    sector: str


@dataclass
class Client:
    name: str
    type: str
    fee_schedule: str
    benchmark: str
    pm: str
    status: str


@dataclass
class NavResult:
    account: str
    client_name: str
    total_market_value: float
    total_cost_basis: float
    total_unrealized_pnl: float
    return_pct: float
    position_count: int
    equity_value: float
    fi_value: float
    equity_pct: float
    fi_pct: float
    daily_fee_accrual: float
    pm: str
    benchmark: str


def load_prices(date_str: str) -> dict[str, float]:
    """Load market prices for given date."""
    file_path: str | Path = rf"{PRICING_DIR}\market_prices_{date_str}.csv"

    # fallback to local
    if not Path(file_path).exists():
        file_path = DATA_DIR / "pricing" / f"market_prices_{date_str}.csv"

    log.info(f"Loading prices from: {file_path}")

    prices: dict[str, float] = {}
    with open(file_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            ticker = row[0]
            close_price = float(row[5])  # CLOSE column
            prices[ticker] = close_price

    log.info(f"Loaded {len(prices)} prices")
    return prices


def load_positions(date_str: str) -> dict[str, list[Position]]:
    """Load portfolio positions."""
    file_path: str | Path = rf"{HOLDINGS_DIR}\portfolio_positions_{date_str}.csv"

    if not Path(file_path).exists():
        file_path = DATA_DIR / "holdings" / f"portfolio_positions_{date_str}.csv"

    log.info(f"Loading positions from: {file_path}")

    positions: dict[str, list[Position]] = {}
    with open(file_path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            acct = row[0]
            positions.setdefault(acct, []).append(
                Position(
                    ticker=row[1],
                    quantity=int(row[4]) if row[4] else 0,
                    avg_cost=float(row[5]) if row[5] else 0.0,
                    asset_class=row[8],
                    sector=row[9],
                )
            )

    log.info(f"Loaded positions for {len(positions)} accounts")
    return positions


def load_clients() -> dict[str, Client]:
    """Load client master data."""
    file_path: str | Path = rf"{CLIENTS_DIR}\client_master.csv"

    if not Path(file_path).exists():
        file_path = DATA_DIR / "clients" / "client_master.csv"

    log.info(f"Loading clients from: {file_path}")

    clients: dict[str, Client] = {}
    with open(file_path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            clients[row[0]] = Client(
                name=row[1],
                type=row[2],
                fee_schedule=row[5],
                benchmark=row[7],
                pm=row[8],
                status=row[9],
            )

    log.info(f"Loaded {len(clients)} clients")
    return clients


def calculate_nav(
    prices: dict[str, float],
    positions: dict[str, list[Position]],
    clients: dict[str, Client],
) -> list[NavResult]:
    """Calculate NAV for each account."""
    log.info("\n" + "=" * 60)
    log.info("CALCULATING NAV")
    log.info("=" * 60)

    nav_results: list[NavResult] = []

    for acct in positions:
        total_market_value = 0.0
        total_cost_basis = 0.0
        position_count = 0
        equity_value = 0.0
        fi_value = 0.0

        for pos in positions[acct]:
            if pos.quantity == 0:
                continue

            ticker = pos.ticker
            qty = pos.quantity
            cost = pos.avg_cost

            # get current price
            if ticker in prices:
                current_price = prices[ticker]
            else:
                # no price found - use avg cost as fallback
                # TODO: this is wrong, should error out
                log.info(f"WARNING: No price for {ticker} in account {acct}, using avg cost")
                current_price = cost

            mkt_val = qty * current_price
            cost_val = qty * cost

            total_market_value += mkt_val
            total_cost_basis += cost_val
            position_count += 1

            if pos.asset_class == "EQUITY":
                equity_value += mkt_val
            elif pos.asset_class == "FIXED_INCOME":
                fi_value += mkt_val

        # calculate fee accrual
        if acct in clients:
            fee_tier = clients[acct].fee_schedule
            annual_fee_rate = FEE_SCHEDULES.get(fee_tier, 0.01)
            # daily fee accrual = annual rate / 365
            daily_fee = total_market_value * annual_fee_rate / 365
        else:
            daily_fee = 0.0
            log.info(f"WARNING: No client record for {acct}")

        # asset allocation percentages
        if total_market_value > 0:
            equity_pct = equity_value / total_market_value * 100
            fi_pct = fi_value / total_market_value * 100
        else:
            equity_pct = 0.0
            fi_pct = 0.0

        client = clients.get(acct)
        nav_result = NavResult(
            account=acct,
            client_name=client.name if client else "UNKNOWN",
            total_market_value=round(total_market_value, 2),
            total_cost_basis=round(total_cost_basis, 2),
            total_unrealized_pnl=round(total_market_value - total_cost_basis, 2),
            return_pct=(
                round((total_market_value - total_cost_basis) / total_cost_basis * 100, 2)
                if total_cost_basis > 0
                else 0
            ),
            position_count=position_count,
            equity_value=round(equity_value, 2),
            fi_value=round(fi_value, 2),
            equity_pct=round(equity_pct, 2),
            fi_pct=round(fi_pct, 2),
            daily_fee_accrual=round(daily_fee, 2),
            pm=client.pm if client else "UNKNOWN",
            benchmark=client.benchmark if client else "UNKNOWN",
        )

        nav_results.append(nav_result)

        # print summary
        log.info(f"\n  {acct} - {nav_result.client_name}")
        log.info(f"    Market Value:     ${total_market_value:>15,.2f}")
        log.info(f"    Cost Basis:       ${total_cost_basis:>15,.2f}")
        log.info(f"    Unrealized P&L:   ${total_market_value - total_cost_basis:>15,.2f}")
        log.info(f"    Return:           {nav_result.return_pct:>15.2f}%")
        log.info(f"    Equity/FI Split:  {equity_pct:>6.1f}% / {fi_pct:.1f}%")
        log.info(f"    Daily Fee:        ${daily_fee:>15,.2f}")

    return nav_results


def write_nav_report(nav_results: list[NavResult], date_str: str) -> None:
    """Write NAV report to CSV."""
    output_path: str | Path = rf"{OUTPUT_DIR}\nav_report_{date_str}.csv"

    if not Path(OUTPUT_DIR).exists():
        output_path = REPORTS_DIR / f"nav_report_{date_str}.csv"

    log.info(f"\nWriting NAV report to: {output_path}")

    total_aum = 0.0
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ACCOUNT",
                "CLIENT_NAME",
                "TOTAL_MKT_VALUE",
                "COST_BASIS",
                "UNREALIZED_PNL",
                "RETURN_PCT",
                "POSITIONS",
                "EQUITY_VALUE",
                "FI_VALUE",
                "EQUITY_PCT",
                "FI_PCT",
                "DAILY_FEE",
                "PM",
                "BENCHMARK",
                "AS_OF_DATE",
                "GENERATED_AT",
            ]
        )

        for nav in nav_results:
            writer.writerow(
                [
                    nav.account,
                    nav.client_name,
                    nav.total_market_value,
                    nav.total_cost_basis,
                    nav.total_unrealized_pnl,
                    nav.return_pct,
                    nav.position_count,
                    nav.equity_value,
                    nav.fi_value,
                    nav.equity_pct,
                    nav.fi_pct,
                    nav.daily_fee_accrual,
                    nav.pm,
                    nav.benchmark,
                    date_str,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )
            total_aum += nav.total_market_value

    log.info("\n" + "=" * 60)
    log.info(f"FIRM-WIDE AUM: ${total_aum:,.2f}")
    log.info(f"Total Accounts: {len(nav_results)}")
    log.info("=" * 60)


def main(argv: list[str]) -> None:
    log.info("=" * 60)
    log.info("MERIDIAN CAPITAL - NAV CALCULATION")
    log.info("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    run_date = argv[1] if len(argv) > 1 else "20240315"
    if not re.fullmatch(r"\d{8}", run_date):
        raise SystemExit(f"Invalid run date {run_date!r}: expected YYYYMMDD")

    # Step 1: Load data
    prices = load_prices(run_date)
    positions = load_positions(run_date)
    clients = load_clients()

    # Step 2: Calculate NAV
    nav_results = calculate_nav(prices, positions, clients)

    # Step 3: Write report
    write_nav_report(nav_results, run_date)

    log.info("\nNAV CALCULATION COMPLETE")


if __name__ == "__main__":
    main(sys.argv)
