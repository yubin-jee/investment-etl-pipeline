# Option A: Pandas + Pydantic Standalone Trade Processor

## Approach

This module is a drop-in replacement for the legacy `process_trades.py` script, refactored as a clean, modular Python script using **Pandas** for data manipulation and **Pydantic v2** for data validation.

Key improvements over the legacy script:

- **No global state** — all data flows through function arguments and return values
- **Proper logging** — uses Python's `logging` module instead of `print` statements
- **Correct T+2 settlement** — uses `pandas.tseries.offsets.BDay` to skip weekends (legacy just added 2 calendar days)
- **O(n) reconciliation** — uses `pd.merge` hash join instead of O(n^2) nested loops
- **Type safety** — full type hints and Pydantic model validation on all trade records
- **Cross-platform paths** — uses `pathlib.Path` instead of hardcoded Windows paths
- **Shared common layer** — imports parsing, validation, settlement, and config from `modernized.common`

## Installation

```bash
pip install -r modernized/requirements_option_a.txt
```

Or install dependencies directly:

```bash
pip install pandas pydantic python-dotenv
```

## Usage

Run as a module from the repository root:

```bash
python -m modernized.option_a_pandas.trade_processor --date 20240315 --config config/batch_config.ini
```

Arguments:

| Argument   | Required | Default              | Description                          |
|------------|----------|----------------------|--------------------------------------|
| `--date`   | No       | Today (YYYYMMDD)     | Run date for trade file selection    |
| `--config` | No       | `config/batch_config.ini` | Path to the batch configuration file |

The processor will:

1. Load configuration from `batch_config.ini`
2. Find and parse the daily trades CSV (`daily_trades_{date}.csv`)
3. Validate trades (deduplication, Pydantic type checks, broker whitelist)
4. Calculate gross and net amounts (BUY adds commission, SELL subtracts)
5. Fix missing settlement dates using T+2 business day calculation
6. Load and reconcile against counterparty confirmation files
7. Write processed output CSV and error log to `reports/`

## Output

- **Processed trades CSV** — `reports/processed_trades_{date}.csv` with columns: `TRADE_ID, ACCT_NUM, TICKER, SIDE, QTY, PRICE, GROSS_AMT, NET_AMT, COMMISSION, TRADE_DATE, SETTLE_DATE, BROKER, STATUS, RECON_STATUS, PROCESSED_AT`
- **Error log** — `reports/trade_errors_{date}.log` listing validation failures

## Programmatic Usage

```python
from pathlib import Path
from modernized.option_a_pandas.trade_processor import process_trades

result = process_trades("20240315", config_path=Path("config/batch_config.ini"))
print(result.model_dump_json(indent=2))
```

## Pros

- **Minimal migration effort** — same execution model as legacy (single Python script), minimal infrastructure changes
- **No infrastructure dependencies** — runs anywhere Python is installed, no orchestrator or scheduler required
- **Easy to understand** — straightforward procedural flow, familiar to the existing team
- **Same execution model** — drop-in replacement that can run under the existing Windows Task Scheduler or cron

## Cons

- **No built-in retry/scheduling** — failures require manual re-runs or external scheduling logic
- **Manual orchestration** — no dependency graph between pipeline stages; ordering is implicit
- **No observability UI** — monitoring relies on log files; no dashboards, alerting, or run history out of the box
- **No data lineage** — no automatic tracking of which inputs produced which outputs
