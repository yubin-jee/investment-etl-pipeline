# Trade Processing Modernization — Option Comparison

This document compares three parallel approaches to modernizing the legacy
`legacy_scripts/process_trades.py` trade-ingestion pipeline. All three are built
on the **same shared `modernized/common/` layer** (Pydantic models, pandas
parsers, validation, T+2 settlement, config loader), so they differ only in
their **orchestration and execution model** — not in business logic. Given the
same input, all three produce identical output.

## The shared architecture

```
                         ┌─────────────────────────────────┐
                         │      modernized/common/          │
                         │  models · parsers · validation   │
                         │  settlement · config             │
                         └───────────────┬─────────────────┘
                                         │ (imported by all)
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                           ▼
   ┌───────────────────┐   ┌───────────────────────┐   ┌───────────────────────┐
   │  Option A          │   │  Option B             │   │  Option C             │
   │  Pandas + Pydantic │   │  Dagster              │   │  Airflow              │
   │  (one script)      │   │  (asset graph)        │   │  (DAG of tasks)       │
   └───────────────────┘   └───────────────────────┘   └───────────────────────┘
```

The pipeline itself is identical everywhere:

```
load CSV ─► validate ─► enrich (amounts + T+2) ─► load confirms ─► reconcile ─► write CSV
```

## Summary table

| Criteria | Option A (Pandas+Pydantic) | Option B (Dagster) | Option C (Airflow) |
|----------|---------------------------|--------------------|--------------------|
| Migration effort | Low | Medium | Medium-High |
| Infrastructure needs | None (just Python) | Dagster webserver | Airflow scheduler + DB + webserver |
| Retry/error handling | Manual (try/except) | Built-in RetryPolicy | Built-in retries per task |
| Observability | Logging only | Full UI with lineage | DAG UI with task logs |
| Date partitioning | Manual (argparse) | Native DailyPartitions | Native execution_date |
| Backfill support | Manual re-run | One-click backfill | CLI backfill command |
| Idempotency | Must implement manually | Asset-level materialization | Must implement manually |
| Learning curve | Minimal | Moderate | Moderate-High |
| Scalability | Single process | Worker pools | Celery/K8s executors |
| Data lineage | None | Full asset graph | Limited (task-level) |
| Testing | Standard pytest | Dagster testing utilities | Airflow test utilities |
| Community/ecosystem | N/A | Growing | Very large |
| Best for | Quick wins, small team | Data-centric pipelines | Complex multi-system orchestration |

## Execution model at a glance

```
 OPTION A — standalone script
   $ python -m modernized.option_a_pandas.trade_processor --date 20240115
   ┌──────────────────────────────────────────────┐
   │ process_trades(): load→validate→enrich→       │
   │ reconcile→write   (one process, top to bottom)│
   └──────────────────────────────────────────────┘
   No scheduler, no UI. You (or cron) run it.

 OPTION B — Dagster asset graph
        raw_trades ─► validated_trades ─► enriched_trades ─┐
                                                            ├─► reconciled_trades
                          counterparty_confirms ───────────┘
   Each box is a materializable, observable @asset with metadata + RetryPolicy.
   Partitioned by day; backfills + lineage in the Dagster UI.

 OPTION C — Airflow DAG
   [FileSensor] ─► load_trades ─► validate_trades ─► enrich_trades ─┐
                                                                     ├─► reconcile ─► write_output
                                            load_confirms ──────────┘
   Scheduled "30 6 * * 1-5". Per-task retries, XCom hand-off, task logs in the UI.
```

## What each option fixes

Every option inherits these fixes from the shared `common/` layer, regardless of
orchestrator:

| Legacy bug | How it's fixed (all options) |
|------------|------------------------------|
| Hardcoded `C:\MeridianData\...` paths | `common.config.load_config()` reads `batch_config.ini` |
| Positional CSV indexing | `common.parsers.load_trades_csv()` (named columns + dtypes) |
| Hand-rolled fixed-width slicing | `common.parsers.load_counterparty_file()` (`pd.read_fwf`) |
| Broken T+2 (ignores weekends) | `common.settlement.calculate_t_plus_2()` (`BDay(2)`) |
| Ad-hoc dict validation | `common.validation` + Pydantic `RawTrade` model |
| O(n²) nested-loop reconciliation | `pd.merge(..., how="left")` hash join — O(n) |
| Global mutable state | Pure functions returning DataFrames / `ProcessingResult` |
| `print()` everywhere | `logging` module / framework-native logging |
| No config usage | `batch_config.ini` actually consumed |

Orchestrator-specific additions:

| | Option A | Option B (Dagster) | Option C (Airflow) |
|---|----------|--------------------|--------------------|
| Retries | manual try/except | `RetryPolicy(max_retries=3, delay=60)` | `retries=3, retry_delay=5m` per task |
| Scheduling | external (cron) | partitioned schedules | `schedule_interval="30 6 * * 1-5"` |
| File-arrival wait | none | sensor/freshness policy | `FileSensor` |
| Observability | logs only | asset graph + metadata UI | DAG/task logs UI |
| Backfill | re-run script per date | one-click partition backfill | `airflow dags backfill` |

## What each option does NOT fix

These are out of scope for the ingestion-layer prototype and remain open work
for any option:

- **Star-schema warehouse / SCD Type 2 history** — all three still write a flat
  output CSV; none builds the dimensional model called for in the migration plan.
- **Holiday-aware settlement** — `calculate_t_plus_2` skips weekends but not
  market holidays (documented TODO to swap in an exchange calendar).
- **Database persistence** — config exposes the SQL Server connection info but
  no option writes to a real database yet.
- **Downstream pipeline** (NAV, position recon, compliance, client reports) —
  only `process_trades` is modernized here.
- **Real-time / streaming** — all three remain batch-oriented.
- **Reference-data services** (CUSIP/ticker resolution, benchmark feeds).

Option-specific gaps:
- **Option A** has no scheduler, UI, lineage, or built-in retries — you bolt on
  cron + monitoring yourself.
- **Option B** requires running the Dagster webserver/daemon to get the UI and
  schedules; it is a newer, smaller ecosystem than Airflow.
- **Option C** has the heaviest infra footprint (scheduler + metadata DB +
  webserver) and the steepest operational learning curve; data lineage is only
  task-level.

## Recommendation

```
   Migration effort  ─────────────────────────────────────────►  capability
   Option A ───────────────► Option B ───────────────► Option C
   (script)                  (Dagster)                 (Airflow)
   quick win                 data-centric sweet spot   heavy orchestration
                                   ▲
                                   │ recommended for Meridian
```

**Recommended: Option B (Dagster).** For Meridian's use case — a data-centric
daily batch with clear stage-to-stage data dependencies, a need for lineage,
observability, and painless backfills, but without an existing heavyweight
orchestration platform to maintain — Dagster hits the best balance. Its
asset-based model maps cleanly onto the load → validate → enrich → reconcile
stages, gives the ops team a UI with row-count/error metadata and one-click
backfills, and provides built-in retries without standing up a separate metadata
database and scheduler the way Airflow requires.

**Use Option A as a stepping stone.** If the team wants to move incrementally,
ship Option A first: it is the lowest-effort, zero-infrastructure path and
immediately retires the worst legacy bugs (hardcoded paths, broken settlement,
O(n²) reconciliation, global state). Because all three options share the same
`common/` layer, migrating from Option A to Option B later is mostly a matter of
wrapping the existing functions in Dagster assets — no business logic changes.

**Choose Option C (Airflow) only if** Meridian later needs to orchestrate many
heterogeneous systems beyond this pipeline (cross-team DAGs, diverse operators,
existing Airflow investment). For a single data pipeline at this scale, its
operational overhead outweighs its benefits.
