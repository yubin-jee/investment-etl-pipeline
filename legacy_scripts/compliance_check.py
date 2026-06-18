#!/usr/bin/env python
"""
Compliance Check Script - Meridian Capital Partners
Checks portfolio positions against compliance rules.

Author: Lisa Park / Dave Ops
NOTE: Rules are loaded from XML because that's what the old
      compliance vendor used. Nobody knows why it's XML.
"""

from __future__ import annotations

import csv
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logging_config import get_logger

log = get_logger(__name__)

# Legacy Windows network drive locations (kept for display; the local fallbacks
# below are used off Windows).
COMPLIANCE_DIR = r"C:\MeridianData\compliance"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "legacy_data"
REPORTS_DIR = BASE_DIR / "reports"


@dataclass
class Rule:
    id: str | None
    severity: str | None
    name: str | None
    description: str | None
    threshold: float | None
    asset_class: str | None
    account_types: list[str] | None
    action: str | None


@dataclass
class Position:
    ticker: str
    quantity: int
    market_value: float
    asset_class: str
    sector: str


@dataclass
class ClientInfo:
    name: str
    type: str


@dataclass
class Violation:
    rule_id: str
    severity: str
    account: str
    client: str
    detail: str
    value: float
    action: str


def load_rules() -> list[Rule]:
    """Load compliance rules from XML file."""
    file_path: str | Path = rf"{COMPLIANCE_DIR}\compliance_rules.xml"

    if not Path(file_path).exists():
        file_path = DATA_DIR / "compliance" / "compliance_rules.xml"

    log.info(f"Loading compliance rules: {file_path}")

    tree = ET.parse(file_path)
    root = tree.getroot()

    rules: list[Rule] = []
    for rule_elem in root.findall("Rule"):
        threshold_elem = rule_elem.find("Threshold")
        asset_class_elem = rule_elem.find("AssetClass")
        account_types_elem = rule_elem.find("AccountTypes")
        rules.append(
            Rule(
                id=rule_elem.get("id"),
                severity=rule_elem.get("severity"),
                name=rule_elem.find("Name").text,
                description=rule_elem.find("Description").text,
                threshold=float(threshold_elem.text) if threshold_elem is not None else None,
                asset_class=asset_class_elem.text if asset_class_elem is not None else None,
                account_types=(
                    account_types_elem.text.split(",") if account_types_elem is not None else None
                ),
                action=rule_elem.find("Action").text,
            )
        )

    log.info(f"Loaded {len(rules)} rules")
    return rules


def load_positions_and_clients(
    date_str: str,
) -> tuple[dict[str, list[Position]], dict[str, ClientInfo]]:
    """Load positions and client data for checking."""
    positions: dict[str, list[Position]] = {}
    clients: dict[str, ClientInfo] = {}

    # load positions
    pos_file = DATA_DIR / "holdings" / f"portfolio_positions_{date_str}.csv"
    with open(pos_file) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            acct = row[0]
            qty = int(row[4]) if row[4] else 0
            mkt_val = float(row[6]) if row[6] else 0.0
            if qty > 0:
                positions.setdefault(acct, []).append(
                    Position(
                        ticker=row[1],
                        quantity=qty,
                        market_value=mkt_val,
                        asset_class=row[8],
                        sector=row[9],
                    )
                )

    # load clients
    client_file = DATA_DIR / "clients" / "client_master.csv"
    with open(client_file) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            clients[row[0]] = ClientInfo(name=row[1], type=row[2])

    return positions, clients


def _client_name(clients: dict[str, ClientInfo], acct: str) -> str:
    client = clients.get(acct)
    return client.name if client else "UNKNOWN"


def check_concentration_limits(
    positions: dict[str, list[Position]], clients: dict[str, ClientInfo]
) -> list[Violation]:
    """RULE-001: Single security concentration limit (10%)."""
    log.info("\nChecking RULE-001: Single Security Concentration...")

    violations: list[Violation] = []
    for acct in positions:
        total_value = sum(p.market_value for p in positions[acct])
        if total_value == 0:
            continue

        for pos in positions[acct]:
            concentration = pos.market_value / total_value
            if concentration > 0.10:
                detail = (
                    f"{pos.ticker} is {round(concentration * 100, 2)}% of portfolio (limit: 10%)"
                )
                violations.append(
                    Violation(
                        rule_id="RULE-001",
                        severity="CRITICAL",
                        account=acct,
                        client=_client_name(clients, acct),
                        detail=detail,
                        value=round(concentration * 100, 2),
                        action="BLOCK_TRADE",
                    )
                )
                log.info(f"  VIOLATION: {acct} - {detail}")

    return violations


def check_sector_concentration(
    positions: dict[str, list[Position]], clients: dict[str, ClientInfo]
) -> list[Violation]:
    """RULE-002: Sector concentration limit (30%)."""
    log.info("\nChecking RULE-002: Sector Concentration...")

    violations: list[Violation] = []
    for acct in positions:
        total_value = sum(p.market_value for p in positions[acct])
        if total_value == 0:
            continue

        # aggregate by sector
        sector_values: dict[str, float] = {}
        for pos in positions[acct]:
            sector_values[pos.sector] = sector_values.get(pos.sector, 0.0) + pos.market_value

        for sector, value in sector_values.items():
            concentration = value / total_value
            if concentration > 0.30:
                detail = (
                    f"{sector} sector is {round(concentration * 100, 2)}% of portfolio (limit: 30%)"
                )
                violations.append(
                    Violation(
                        rule_id="RULE-002",
                        severity="HIGH",
                        account=acct,
                        client=_client_name(clients, acct),
                        detail=detail,
                        value=round(concentration * 100, 2),
                        action="ALERT",
                    )
                )
                log.info(f"  VIOLATION: {acct} - {detail}")

    return violations


def check_fi_minimum(
    positions: dict[str, list[Position]], clients: dict[str, ClientInfo]
) -> list[Violation]:
    """RULE-003: Fixed income minimum for retirement/pension accounts."""
    log.info("\nChecking RULE-003: Fixed Income Minimum...")

    violations: list[Violation] = []
    for acct in positions:
        client = clients.get(acct)
        client_type = client.type if client else ""
        if client_type not in ["401K", "PENSION"]:
            continue

        total_value = sum(p.market_value for p in positions[acct])
        fi_value = sum(p.market_value for p in positions[acct] if p.asset_class == "FIXED_INCOME")

        if total_value == 0:
            continue

        fi_pct = fi_value / total_value
        if fi_pct < 0.15:
            detail = (
                f"Fixed income is {round(fi_pct * 100, 2)}% "
                f"(minimum: 15% for {client_type} accounts)"
            )
            violations.append(
                Violation(
                    rule_id="RULE-003",
                    severity="MEDIUM",
                    account=acct,
                    client=_client_name(clients, acct),
                    detail=detail,
                    value=round(fi_pct * 100, 2),
                    action="ALERT",
                )
            )
            log.info(f"  VIOLATION: {acct} - {detail}")

    return violations


def write_compliance_report(violations: list[Violation], date_str: str) -> None:
    """Write compliance report."""
    output_path = REPORTS_DIR / f"compliance_report_{date_str}.csv"

    log.info(f"\nWriting compliance report to: {output_path}")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "RULE_ID",
                "SEVERITY",
                "ACCOUNT",
                "CLIENT",
                "DETAIL",
                "VALUE",
                "ACTION",
                "AS_OF_DATE",
                "GENERATED_AT",
            ]
        )

        for v in violations:
            writer.writerow(
                [
                    v.rule_id,
                    v.severity,
                    v.account,
                    v.client,
                    v.detail,
                    v.value,
                    v.action,
                    date_str,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

    # print summary
    critical_count = len([v for v in violations if v.severity == "CRITICAL"])
    high_count = len([v for v in violations if v.severity == "HIGH"])
    medium_count = len([v for v in violations if v.severity == "MEDIUM"])

    log.info("\n" + "=" * 60)
    log.info("COMPLIANCE SUMMARY")
    log.info("=" * 60)
    log.info(f"  CRITICAL: {critical_count}")
    log.info(f"  HIGH:     {high_count}")
    log.info(f"  MEDIUM:   {medium_count}")
    log.info(f"  TOTAL:    {len(violations)}")

    if critical_count > 0:
        log.info("\n  *** CRITICAL VIOLATIONS FOUND - TRADING MAY BE RESTRICTED ***")

    log.info("=" * 60)


def main(argv: list[str]) -> int:
    log.info("=" * 60)
    log.info("MERIDIAN CAPITAL - COMPLIANCE CHECK")
    log.info("Run Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 60)

    run_date = argv[1] if len(argv) > 1 else "20240315"

    # Load rules and data
    load_rules()
    positions, clients = load_positions_and_clients(run_date)

    # Run checks
    violations: list[Violation] = []
    violations += check_concentration_limits(positions, clients)
    violations += check_sector_concentration(positions, clients)
    violations += check_fi_minimum(positions, clients)

    # Write report
    write_compliance_report(violations, run_date)

    if violations:
        log.info("\nCOMPLIANCE CHECK: VIOLATIONS FOUND")
        return 1

    log.info("\nCOMPLIANCE CHECK: ALL CLEAR")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
