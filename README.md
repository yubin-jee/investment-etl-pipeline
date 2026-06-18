# Meridian Capital Partners — Legacy Data Processing System

> **⚠️ This is a legacy codebase that needs to be modernized through an ETL migration.**

## Company Background

**Meridian Capital Partners** is a mid-size investment management firm managing ~$2M+ AUM across six client accounts including family trusts, hedge funds, retirement plans, endowments, a family office, and a pension fund. The firm has been operating since 2017 and uses a collection of homegrown Python scripts and SQL Server stored procedures for its daily operations.

## Current State (Legacy System)

### Architecture
The current system consists of:
- **Batch Python scripts** running on a single Windows Server 2022 via Task Scheduler
- **Microsoft SQL Server 2022** for storage (no ORM, raw SQL strings)
- **Flat file processing** — CSV, fixed-width (.dat), and XML files from various counterparties
- **Network drive storage** (mapped `C:\MeridianData\`) for all input/output files
- **Manual Excel-based reporting** — scripts generate text files that ops team manually copies into Excel templates

### Daily Processing Pipeline
The system runs a sequential batch process every morning at 6:30 AM EST:

| Step | Script | Description |
|------|--------|-------------|
| 1 | `process_trades.py` | Loads daily trade CSV files, validates, calculates amounts, reconciles with counterparty confirmations |
| 2 | `calc_nav.py` | Calculates Net Asset Value for all client accounts using market prices and positions |
| 3 | `reconciliation.py` | Compares internal positions with custodian (State Street) positions |
| 4 | `compliance_check.py` | Checks portfolios against concentration limits and allocation rules |
| 5 | `generate_client_reports.py` | Generates text-based performance reports for clients |

All scripts are orchestrated by `daily_batch.py` which runs them sequentially via `os.system()`.

### Data Sources

| Source | Format | Description |
|--------|--------|-------------|
| `daily_trades_*.csv` | CSV | Daily trade files from internal OMS |
| `counterparty_confirms.dat` | Fixed-width | Trade confirmations from brokers (Goldman, Morgan Stanley, JP Morgan, etc.) |
| `portfolio_positions_*.csv` | CSV | Internal position records |
| `custodian_positions_*.txt` | Fixed-width text | Position report from State Street custodian |
| `market_prices_*.csv` | CSV | End-of-day pricing from Bloomberg |
| `fx_rates_*.csv` | CSV | FX rates from Reuters |
| `client_master.csv` | CSV | Client/account master data |
| `compliance_rules.xml` | XML | Compliance rules from legacy vendor system |

### Known Issues & Technical Debt

#### Critical
- **No error handling** — scripts use bare `except` or no try/catch at all
- **No logging** — everything uses `print()` statements
- **Hardcoded Windows paths** — `C:\MeridianData\` paths throughout all scripts
- **No data validation framework** — ad-hoc validation in each script
- **No tests** — zero unit or integration tests
- **Date handling is broken** — dates stored as strings (`MM/DD/YYYY`), T+2 settlement calculation ignores weekends/holidays
- **Duplicate detection is fragile** — uses in-memory list, not idempotent across runs
- **Global mutable state** — scripts use global variables extensively

#### High
- **No database constraints** — no primary keys, foreign keys, or indexes on SQL tables
- **Position history not maintained** — positions overwritten daily with no audit trail
- **CUSIP-to-ticker mapping is hardcoded** — manual dictionary in `reconciliation.py`
- **Benchmark returns hardcoded** — monthly returns manually typed into script
- **Cross-year date queries broken** — stored procedure does string comparison on `MM/DD/YYYY` dates
- **Fee calculation uses 365 days** — should use actual business days
- **No retry logic** — if a file isn't ready at 6:30 AM, batch fails

#### Medium
- **No configuration management** — `batch_config.ini` exists but isn't used by scripts
- **Email notifications broken** — former employee's email still in config
- **Reports are text files** — ops team manually copies into Excel templates
- **No data lineage** — impossible to trace where a number came from
- **No monitoring/alerting** — failures discovered when clients call

## Directory Structure

```
investment-etl-pipeline/
├── README.md                           # This file
├── requirements.txt                    # Dependencies (currently none - stdlib only)
├── config/
│   └── batch_config.ini                # Configuration (mostly unused)
├── legacy_data/                        # Sample data files
│   ├── trades/
│   │   ├── daily_trades_20240315.csv   # Daily trade file (with intentional data issues)
│   │   ├── daily_trades_20240318.csv   # Another day's trades
│   │   └── counterparty_confirms.dat   # Fixed-width broker confirmations
│   ├── holdings/
│   │   ├── portfolio_positions_20240315.csv  # Internal positions
│   │   └── custodian_positions_20240315.txt  # State Street custodian report
│   ├── clients/
│   │   └── client_master.csv           # Client/account master data
│   ├── pricing/
│   │   ├── market_prices_20240315.csv  # Bloomberg EOD prices
│   │   └── fx_rates_20240315.csv       # Reuters FX rates
│   └── compliance/
│       └── compliance_rules.xml        # Compliance rules (XML from legacy vendor)
├── legacy_scripts/                     # The scripts that need to be migrated
│   ├── daily_batch.py                  # Batch orchestrator
│   ├── process_trades.py               # Trade processing & counterparty reconciliation
│   ├── calc_nav.py                     # NAV calculation
│   ├── reconciliation.py               # Position reconciliation vs custodian
│   ├── compliance_check.py             # Compliance rule checking
│   └── generate_client_reports.py      # Client performance report generation
├── sql/
│   ├── create_tables.sql               # Database schema (no constraints)
│   └── stored_procedures.sql           # Stored procedures (with known bugs)
├── reports/                            # Generated reports (gitignored)
└── logs/                               # Log files (gitignored)
```

## Running the Legacy System

The scripts can be run locally for demo purposes using the sample data:

```bash
# Run the full daily batch
python legacy_scripts/daily_batch.py 20240315

# Or run individual scripts
python legacy_scripts/process_trades.py 20240315
python legacy_scripts/calc_nav.py 20240315
python legacy_scripts/reconciliation.py 20240315
python legacy_scripts/compliance_check.py 20240315
python legacy_scripts/generate_client_reports.py 20240315
```

Output reports are written to the `reports/` directory.

## Migration Objectives

The goal is to modernize this legacy system into a production-grade ETL pipeline. Key migration requirements:

### 1. Data Pipeline Modernization
- Replace batch scripts with a proper ETL framework (e.g., Apache Airflow, Prefect, or Dagster)
- Implement proper error handling, logging, and retry logic
- Add data validation and quality checks at each stage
- Support incremental/idempotent processing

### 2. Data Model Redesign
- Design a proper star schema data warehouse
- Add primary keys, foreign keys, and appropriate indexes
- Implement SCD Type 2 for client and position history
- Convert all dates from strings to proper date types
- Add data lineage and audit trails

### 3. Integration Improvements
- Replace hardcoded file paths with configurable data connectors
- Automate CUSIP/SEDOL/ticker resolution via reference data service
- Replace hardcoded benchmark returns with market data feed
- Add support for real-time trade processing (not just batch)

### 4. Reporting & Analytics
- Replace text-based reports with automated PDF/Excel generation
- Build analytics views for portfolio performance attribution
- Add dashboard-ready aggregations
- Implement proper benchmark comparison methodology

### 5. Compliance & Risk
- Implement rules engine instead of hardcoded compliance checks
- Add pre-trade compliance (not just post-trade)
- Proper settlement date calculation with holiday calendar
- Real-time position monitoring

### 6. Operational Excellence
- Add comprehensive test suite (unit + integration)
- Implement CI/CD pipeline
- Add monitoring, alerting, and observability
- Documentation and runbooks

## Data Quality Issues in Sample Data

The sample data intentionally includes several issues that the migration should address:
- **Duplicate trade** (T-20240315-001 and T-20240315-015 are identical)
- **Missing settle date** (T-20240315-011)
- **Missing price** (T-20240318-008 ADBE trade has no price)
- **Failed trade** (T-20240315-009 with FAILED status)
- **Zero-quantity positions** (some accounts have 0-qty rows)
- **Price discrepancies** between position file and pricing file (BND)
- **Inconsistent data formats** across different file types
