# Option A: Pandas + Pydantic Standalone Processor

## Approach

A direct, refactored replacement for `legacy_scripts/process_trades.py` using modern Python libraries. No orchestration framework required — just a well-structured Python script.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Option A Pipeline Flow                       │
│                                                                 │
│  CSV File ──► load_trades_csv() ──► validate_trades()           │
│                                         │                       │
│                                    ┌────┴────┐                  │
│                                    ▼         ▼                  │
│                              valid_df    error_df → error log   │
│                                    │                            │
│                        fix_settlement_dates()                   │
│                                    │                            │
│                        calculate_amounts()                      │
│                                    │                            │
│  .dat File ──► load_counterparty_file() ──┐                     │
│                                           ▼                     │
│                              reconcile (pd.merge)               │
│                                    │                            │
│                                    ▼                            │
│                            Output CSV + Summary                 │
└─────────────────────────────────────────────────────────────────┘
```

## Key Improvements over Legacy

| Legacy Issue | How Option A Fixes It |
|---|---|
| Global mutable state | All data passed as function args/returns |
| `print()` logging | Python `logging` module with configurable levels |
| Hardcoded Windows paths | Config file driven via `batch_config.ini` |
| O(n²) reconciliation | O(n) hash join via `pd.merge()` |
| Broken T+2 calculation | `pd.tseries.offsets.BDay(2)` skips weekends |
| No data validation | Pydantic v2 model validation per row |
| `csv.reader` positional indexing | `pd.read_csv()` with named columns and dtypes |
| Manual fixed-width parsing | `pd.read_fwf()` with column specs |
| No error tracking | Separate error DataFrame written to CSV |

## How to Run

```bash
# Install dependencies
pip install -r modernized/requirements_option_a.txt

# Run with sample data
python -m modernized.option_a_pandas.trade_processor \
    --date 20240315 \
    --config config/batch_config.ini \
    --trade-file legacy_data/trades/daily_trades_20240315.csv \
    --confirm-file legacy_data/trades/counterparty_confirms.dat \
    --output-dir reports/

# Run with test data
python -m modernized.option_a_pandas.trade_processor \
    --date 20240115 \
    --config config/batch_config.ini \
    --trade-file modernized/test_data/daily_trades_20240115.csv \
    --confirm-file modernized/test_data/counterparty_confirms_20240115.dat \
    --output-dir reports/
```

## Pros

- **Minimal migration effort** — closest to the existing code structure
- **No infrastructure requirements** — just Python + pip
- **Easy to understand** — straightforward procedural flow
- **Fast onboarding** — any Python developer can maintain it
- **Testable** — pure functions, easy to unit test with pytest

## Cons

- **No built-in scheduling** — requires external cron/Task Scheduler
- **No built-in retry logic** — must implement try/except manually
- **No observability UI** — relies on log files only
- **No backfill support** — must manually re-run for each date
- **No data lineage** — no automatic tracking of data provenance
- **Single-process** — no parallelism for large file volumes
