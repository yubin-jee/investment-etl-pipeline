# Modernization Options: Side-by-Side Comparison

## Summary Table

| Criteria | Option A (Pandas+Pydantic) | Option B (Dagster) | Option C (Airflow) |
|----------|---------------------------|--------------------|--------------------|
| Migration effort | Low | Medium | Medium-High |
| Infrastructure needs | None (just Python) | Dagster webserver + daemon | Airflow scheduler + DB + webserver |
| Retry/error handling | Manual (try/except) | Built-in RetryPolicy | Built-in retries per task |
| Observability | Logging only | Full UI with lineage | DAG UI with task logs |
| Date partitioning | Manual (argparse) | Native DailyPartitions | Native execution_date |
| Backfill support | Manual re-run per date | One-click backfill in UI | CLI backfill command |
| Idempotency | Must implement manually | Asset-level materialization | Must implement manually |
| Learning curve | Minimal | Moderate | Moderate-High |
| Scalability | Single process | Worker pools | Celery/K8s executors |
| Data lineage | None | Full asset graph | Limited (task-level) |
| Testing | Standard pytest | Dagster testing utilities | Airflow test utilities |
| Community/ecosystem | N/A | Growing | Very large |
| Best for | Quick wins, small team | Data-centric pipelines | Complex multi-system orchestration |

## Architecture Comparison

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         OPTION A: Standalone Script                       │
│                                                                           │
│   $ python trade_processor.py --date 20240315                            │
│                                                                           │
│   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐   ┌────────┐  │
│   │  Load   │──►│ Validate │──►│ Enrich  │──►│Reconcile │──►│ Output │  │
│   └─────────┘   └──────────┘   └─────────┘   └──────────┘   └────────┘  │
│                                                                           │
│   No infrastructure. Just a Python process.                              │
└───────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│                      OPTION B: Dagster Asset Graph                        │
│                                                                           │
│   ┌─────────────────────────────────────────────────────────────────┐     │
│   │                    Dagster Webserver (UI)                       │     │
│   │  ┌────────────┐ ┌──────────────┐ ┌────────────┐               │     │
│   │  │ Asset Graph │ │ Run History  │ │ Partitions │               │     │
│   │  └────────────┘ └──────────────┘ └────────────┘               │     │
│   └──────────────────────────┬──────────────────────────────────────┘     │
│                              │                                           │
│   ┌──────────────────────────▼──────────────────────────────────────┐     │
│   │                    Dagster Daemon                               │     │
│   │  Schedules ─► Sensors ─► Run Coordinator                       │     │
│   └──────────────────────────┬──────────────────────────────────────┘     │
│                              │                                           │
│   ┌──────────────────────────▼──────────────────────────────────────┐     │
│   │  @asset raw_trades ──► @asset validated ──► @asset enriched    │     │
│   │                                                      │         │     │
│   │  @asset confirms ───────────────────────► @asset reconciled    │     │
│   └────────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│                       OPTION C: Airflow DAG                               │
│                                                                           │
│   ┌─────────────────────────────────────────────────────────────────┐     │
│   │                    Airflow Webserver (UI)                       │     │
│   │  ┌──────────┐ ┌───────────┐ ┌────────┐ ┌──────────┐           │     │
│   │  │ DAG View │ │ Tree View │ │ Gantt  │ │ Task Log │           │     │
│   │  └──────────┘ └───────────┘ └────────┘ └──────────┘           │     │
│   └──────────────────────────┬──────────────────────────────────────┘     │
│                              │                                           │
│   ┌──────────────────────────▼──────────────────────────────────────┐     │
│   │              Airflow Scheduler + Metadata DB                   │     │
│   └──────────────────────────┬──────────────────────────────────────┘     │
│                              │                                           │
│   ┌──────────────────────────▼──────────────────────────────────────┐     │
│   │  FileSensor ──► LoadValidate ──► Enrich ──► Reconcile ──► Write│     │
│   │  (waits for     (PythonOp)      (PythonOp)  (PythonOp)  (PythonOp)  │
│   │   trade file)                                                  │     │
│   └────────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────────┘
```

## What Each Option Fixes

### Legacy Bug: Broken T+2 Settlement Date Calculation

The legacy code adds 2 calendar days and uses a crude `if day > 30` overflow check, ignoring weekends entirely.

| Option | Fix |
|--------|-----|
| **All three** | Use `common.settlement.calculate_t_plus_2()` which calls `pd.tseries.offsets.BDay(2)` to correctly skip weekends. Holiday calendar support noted for future enhancement. |

### Legacy Bug: O(n²) Nested-Loop Reconciliation

The legacy code iterates all trades × all confirms in a nested for-loop.

| Option | Fix |
|--------|-----|
| **All three** | Use `pd.merge(trades, confirms, on='trade_id', how='left')` for O(n) hash join via the shared common layer. |

### Legacy Bug: Global Mutable State

The legacy code uses global lists (`all_trades`, `processed_ids`) and counters (`error_count`, `duplicate_count`).

| Option | Fix |
|--------|-----|
| **A** | All data passed as function arguments/returns. No globals. |
| **B** | Each `@asset` is a pure function receiving DataFrames as inputs. |
| **C** | Each task function receives context via `**kwargs`. Intermediate data in temp files. |

### Legacy Bug: Hardcoded Windows Paths

The legacy code hardcodes `C:\MeridianData\` throughout.

| Option | Fix |
|--------|-----|
| **All three** | Use `common.config.load_config()` to read from `batch_config.ini`. CLI overrides available. |

### Legacy Bug: No Error Handling or Logging

The legacy code uses `print()` and bare `except`.

| Option | Fix |
|--------|-----|
| **A** | Python `logging` module with configurable levels. Structured error DataFrame. |
| **B** | `context.log.info()` integrated into Dagster UI. Asset metadata for error counts. |
| **C** | Python `logging` + Airflow UI task logs. `on_failure_callback` for alerting. |

### Legacy Bug: No Data Validation

The legacy code does ad-hoc `if` checks with no schema enforcement.

| Option | Fix |
|--------|-----|
| **All three** | Pydantic v2 model validation per row via `common.validation.validate_trades()`. Type constraints, `gt=0` validators, `Literal` side enforcement. |

### Legacy Bug: No Retry Logic

If a file isn't ready at 6:30 AM, the batch fails with no retry.

| Option | Fix |
|--------|-----|
| **A** | Manual — must wrap in try/except or external retry mechanism. |
| **B** | `RetryPolicy(max_retries=3, delay=60)` per asset. |
| **C** | `retries=3, retry_delay=timedelta(minutes=5)` per task. `FileSensor` waits for input. |

### Legacy Bug: No Configuration Management

`batch_config.ini` exists but is never read by any script.

| Option | Fix |
|--------|-----|
| **All three** | `common.config.load_config()` reads the INI file. Option B wraps it in `ConfigurableResource`. |

## What Each Option Doesn't Fix

These limitations exist regardless of which option is chosen and require separate effort:

| Limitation | Details |
|---|---|
| **Holiday calendar** | T+2 skips weekends but not market holidays (NYSE, SIFMA). Requires a holiday calendar data source. |
| **SQL Server integration** | None of the options connect to the database. A database layer (SQLAlchemy, etc.) is a separate workstream. |
| **Real-time processing** | All three are batch-oriented. Real-time would require a streaming architecture (Kafka, Flink, etc.). |
| **CUSIP/SEDOL resolution** | Still requires a reference data service or lookup table. |
| **PDF/Excel reporting** | Output is still CSV. Report generation is a separate module. |
| **Pre-trade compliance** | Compliance checking is a separate script (`compliance_check.py`). |
| **Position history / SCD** | Requires database schema changes (SCD Type 2). |
| **Multi-currency support** | Currency is parsed but not used for FX conversion. |

## Recommendation

### Primary: Option B (Dagster)

Dagster is recommended for Meridian's use case because:

1. **Data-centric design** — Assets map naturally to Meridian's data pipeline stages (trades → validated → enriched → reconciled)
2. **Built-in lineage** — Critical for an investment firm where regulators may ask "where did this number come from?"
3. **Partition-native** — Daily partitions are first-class, with one-click backfill for historical reprocessing
4. **Observability** — The web UI provides immediate visibility into pipeline health without building custom dashboards
5. **Moderate infrastructure** — Less overhead than Airflow (no separate metadata DB required for development)
6. **Growing ecosystem** — Active development, strong documentation, and increasing adoption in financial services

### Stepping Stone: Option A First

If the team wants to move incrementally:

```
Phase 1 (Week 1-2):     Deploy Option A
                         ├── Immediate bug fixes (T+2, reconciliation)
                         ├── Proper logging and error handling
                         └── Config-driven, no more hardcoded paths

Phase 2 (Week 3-4):     Migrate to Option B (Dagster)
                         ├── Wrap Option A logic in @asset decorators
                         ├── Add partitioning and scheduling
                         └── Deploy Dagster webserver for observability

Phase 3 (Month 2+):     Extend the pipeline
                         ├── Add database integration
                         ├── Add remaining scripts (NAV, recon, compliance)
                         └── Add monitoring and alerting
```

This approach provides immediate value (bug fixes, better logging) while building toward the full Dagster pipeline.

### When to Choose Option C (Airflow)

Choose Airflow if:
- The team already has Airflow infrastructure deployed
- The pipeline needs to orchestrate non-data tasks (API calls, notifications, external systems)
- The organization uses Airflow for other workflows and wants a single orchestration platform
- Kubernetes-based scaling is a hard requirement
