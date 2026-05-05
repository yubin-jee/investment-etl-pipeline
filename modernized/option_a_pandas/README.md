# Option A: Pandas + Pydantic Standalone Trade Processor

## Overview

A standalone Python script that replaces the legacy `legacy_scripts/process_trades.py` with a clean, functional implementation built on **Pandas** for data manipulation and **Pydantic v2** for structured validation.

This option reuses the shared `modernized/common/` layer for configuration loading, CSV/fixed-width parsing, trade validation, and T+2 settlement-date calculation — keeping the processor itself focused on orchestration and business logic.

### Architecture

```
modernized/
├── common/              # Shared layer (config, parsers, validation, settlement, models)
└── option_a_pandas/
    ├── __init__.py
    ├── trade_processor.py   # Main processor script
    └── README.md
```

### Processing Pipeline

1. **Load config** — reads `batch_config.ini` via `common.config.load_config`.
2. **Read trades** — ingests daily CSV via `common.parsers.load_trades_csv`.
3. **Validate** — deduplicates and validates via `common.validation.validate_trades` (Pydantic-backed).
4. **Calculate amounts** — computes `gross_amount` and `net_amount` (BUY adds commission, SELL subtracts).
5. **Fill settlement dates** — applies T+2 business-day logic via `common.settlement.calculate_t_plus_2`.
6. **Load confirms** — parses fixed-width broker file via `common.parsers.load_counterparty_file`.
7. **Reconcile** — O(n) hash-join on `trade_id` (replaces legacy O(n²) nested loop).
8. **Write output** — produces `processed_trades_YYYYMMDD.csv` in the reports directory.
9. **Write error log** — produces `trade_errors_YYYYMMDD.csv` for validation failures.

## How to Run

```bash
# Install dependencies
pip install -r modernized/requirements_option_a.txt

# Run against a specific date (from repo root)
python -m modernized.option_a_pandas.trade_processor --date 20240315 --config config/batch_config.ini

# Run with default config path
python -m modernized.option_a_pandas.trade_processor --date 20240315

# Run against test data
python -m modernized.option_a_pandas.trade_processor --date 20240115 --config config/batch_config.ini
```

### Arguments

| Flag       | Required | Default                    | Description                      |
|------------|----------|----------------------------|----------------------------------|
| `--date`   | Yes      | —                          | Run date in `YYYYMMDD` format    |
| `--config` | No       | `config/batch_config.ini`  | Path to configuration INI file   |

### Output

- **Report**: `reports/processed_trades_YYYYMMDD.csv` — processed trades with reconciliation status.
- **Error log**: `reports/trade_errors_YYYYMMDD.csv` — rows that failed validation.

## Pros

- **Minimal dependencies** — only Pandas, Pydantic, and python-dotenv.
- **Easy to understand** — single script, no framework overhead, straightforward control flow.
- **Low migration effort** — closest in structure to the legacy script; team can adopt quickly.
- **Familiar to team** — standard Python data-science tooling with no new paradigms to learn.
- **Testable** — pure functions with explicit inputs/outputs; no global state.

## Cons

- **No built-in orchestration** — no DAG, no dependency management between pipeline stages.
- **No retry logic** — failures require manual re-runs; no automatic backfill.
- **No UI/observability** — no dashboard, no run history, no alerting beyond log files.
- **Manual scheduling** — requires cron / Task Scheduler; no native scheduler integration.
- **Single-machine** — no distributed execution; scaling requires external tooling.
