# Trade Processing Pipeline — Modernization Options

This directory contains three self-contained modernization approaches for the
legacy trade processing pipeline (`legacy_scripts/process_trades.py`). All three
process the same input data and produce equivalent output, enabling side-by-side
comparison.

## Quick Start

```bash
# Install dependencies
pip install pandas sqlalchemy pydantic python-dotenv watchdog pytest

# Run the comparison harness
python -m modernized.compare --date 20240315

# Run individual options
python -m modernized.option_a_pandas.process_trades --date 20240315
python -m modernized.option_c_event_driven.watcher --watch-dir ./legacy_data/trades

# Run tests
pytest tests/ -v
```

## Architecture Overview

### Shared Foundation (`modernized/shared/`)

All three options share common components to avoid code duplication:

```
modernized/shared/
├── models.py        # Pydantic models: Trade, CounterpartyConfirm, ReconResult
├── parsers.py       # CSV and fixed-width file parsers
├── validators.py    # Duplicate detection, broker validation, T+2 calculation
├── reconciler.py    # Hash-join reconciliation (O(n+m) vs legacy O(n*m))
└── db.py            # SQLAlchemy ORM model and session management
```

### Option A: pandas + SQLAlchemy (Minimal Lift)

```
  daily_trades.csv ──> parse_trade_csv()
                            │
                       validate_trades()
                            │
                    calculate_amounts()  [vectorized via pandas]
                            │
  confirms.dat ────> parse_counterparty_dat()
                            │
                       reconcile()  [hash-join O(n+m)]
                          /    \
                   to_csv()    to_db()  [SQLAlchemy upsert]
```

**Best for**: Immediate drop-in replacement with minimal infrastructure change.
Single script, runs via cron or scheduler just like the legacy code.

### Option B: Airflow DAG (ETL Framework)

```
  ┌──────────────────────────────────────────────────────────┐
  │  Airflow DAG: trade_processing_pipeline                  │
  │  Schedule: 30 6 * * 1-5  (weekdays at 6:30 AM)          │
  │                                                          │
  │  load_trades ──> validate ──> calculate_amounts          │
  │                                      │                   │
  │                parse_confirms ───────┤                   │
  │                                      │                   │
  │                                 reconcile                │
  │                                /         \               │
  │                         write_db    write_csv            │
  │                                                          │
  │  Retries: 2x at 5-minute intervals                      │
  │  Monitoring: Airflow UI, email on failure                │
  └──────────────────────────────────────────────────────────┘
```

**Best for**: Teams that need scheduling, monitoring, retry logic, and DAG
versioning. Requires Airflow infrastructure.

### Option C: Event-Driven (Watchdog / Cloud Triggers)

```
                      ┌──────────────────────┐
  File system event ──│   TradeFileHandler    │
  (daily_trades.csv)  │  (dedup by SHA-256)  │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │   TradeProcessor     │
                      │   State Machine:     │
                      │   IDLE               │
                      │    └─> WAITING_FOR_* │
                      │         └─> PROCESSING│
                      │              └─> DONE │
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │   Shared Pipeline    │
                      │   parse → validate   │
                      │   → calc → reconcile │
                      │   → output           │
                      └──────────────────────┘
```

**Cloud equivalents**:
| Local (watchdog) | AWS | Azure | GCP |
|---|---|---|---|
| File watcher | S3 event notification | Blob Storage trigger | Cloud Storage trigger |
| Processor | Lambda / Step Functions | Azure Functions | Cloud Functions / Cloud Run |
| Dead letter | Local directory | SQS DLQ | Service Bus DLQ | Pub/Sub DLQ |

**Best for**: Cloud-native deployments, real-time processing, elimination of
fixed-schedule dependencies.

## Comparison Matrix

| Criterion | Legacy | Option A | Option B | Option C |
|---|---|---|---|---|
| **Complexity** | Low (single script) | Low (single script) | Medium (DAG + tasks) | Medium (watcher + processor) |
| **Infrastructure** | Windows Task Scheduler | cron / any scheduler | Airflow cluster | watchdog / cloud triggers |
| **Scalability** | Poor (O(n*m) recon) | Good (vectorized) | Excellent (horizontal workers) | Excellent (serverless) |
| **Maintainability** | Poor (global state) | Good (typed, tested) | Excellent (modular tasks) | Good (state machine) |
| **Migration Effort** | N/A | 1-2 days | 1-2 weeks (with Airflow setup) | 3-5 days |
| **Error Handling** | print() to stdout | Structured logging | Airflow retry + alerting | Dead-letter + logging |
| **Idempotency** | No | Yes (upsert) | Yes (task-level) | Yes (hash dedup) |
| **T+2 Bug** | Broken | Fixed | Fixed | Fixed |
| **Recon Complexity** | O(n*m) | O(n+m) | O(n+m) | O(n+m) |
| **Testability** | Difficult | Good | Excellent | Good |

## Key Bug Fixes

### 1. T+2 Settlement Date (process_trades.py lines 92-102)

**Legacy bug**: Uses `day + 2` with a `day > 30` heuristic for month-end.
Ignores weekends entirely.

```python
# Legacy (BROKEN):
day = int(parts[1]) + 2
if day > 30:
    day = day - 30
    month = month + 1
```

**Fix**: Uses `pandas.tseries.offsets.BDay(2)` for proper business-day
calculation that handles weekends, month boundaries, and year boundaries.

### 2. O(n*m) Reconciliation (process_trades.py lines 223-248)

**Legacy**: Nested loop iterating all confirms for every trade.

**Fix**: Dictionary-based lookup (hash-join) giving O(n+m) complexity.

### 3. Duplicate Detection (process_trades.py line 68)

**Legacy**: `if t["trade_id"] in processed_ids` where `processed_ids` is a list
— O(n) lookup per check.

**Fix**: Set-based lookup — O(1) per check.

## Recommendation

### For Meridian Capital Partners Today

**Option A (pandas + SQLAlchemy)** is the recommended starting point:
- Minimal infrastructure change — replaces the single legacy script
- Immediate bug fixes (T+2, reconciliation performance)
- Structured logging and env-var config
- 1-2 day migration effort

### Migration Path

```
Phase 1 (Week 1-2):  Deploy Option A as drop-in replacement
                     ├── Replace hardcoded paths with env vars
                     ├── Fix T+2 settlement bug
                     └── Add structured logging

Phase 2 (Week 3-4):  Evaluate infrastructure needs
                     ├── Growing team → Option B (Airflow)
                     └── Moving to cloud → Option C (event-driven)

Phase 3 (Week 5+):   Migrate remaining legacy scripts
                     ├── calc_nav.py
                     ├── reconciliation.py
                     └── compliance_check.py
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test suites
pytest tests/test_shared_models.py -v      # Model validation
pytest tests/test_shared_parsers.py -v     # File parsing
pytest tests/test_shared_validators.py -v  # Validation + T+2
pytest tests/test_shared_reconciler.py -v  # Reconciliation
pytest tests/test_option_a.py -v           # Option A end-to-end
pytest tests/test_option_b.py -v           # Airflow task functions
pytest tests/test_option_c.py -v           # Event-driven + state machine
```

## Configuration

Copy `.env.example` to `.env` and configure:

```env
TRADE_DIR=./legacy_data/trades/
OUTPUT_DIR=./reports/
DB_CONNECTION_STRING=sqlite:///trades.db
LOG_LEVEL=INFO
```
