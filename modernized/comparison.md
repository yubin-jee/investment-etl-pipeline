# Trade Processing Modernization — Comparison of Approaches

This document compares three modernization options for replacing the legacy `process_trades.py` script. All three options share the same common layer (`modernized/common/`) and produce identical output given the same input.

## Architecture Overview

```
                          ┌─────────────────────────────────┐
                          │     SHARED COMMON LAYER         │
                          │  modernized/common/             │
                          │                                 │
                          │  ┌───────────┐  ┌────────────┐  │
                          │  │ models.py │  │ parsers.py │  │
                          │  │ (Pydantic)│  │ (pandas)   │  │
                          │  └───────────┘  └────────────┘  │
                          │  ┌────────────┐ ┌────────────┐  │
                          │  │validation. │ │settlement. │  │
                          │  │py          │ │py (BDay)   │  │
                          │  └────────────┘ └────────────┘  │
                          │  ┌────────────┐                 │
                          │  │ config.py  │                 │
                          │  └────────────┘                 │
                          └──────────┬──────────────────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
        ┌────────▼────────┐ ┌───────▼────────┐ ┌───────▼────────┐
        │   OPTION A      │ │   OPTION B     │ │   OPTION C     │
        │ Pandas+Pydantic │ │   Dagster      │ │   Airflow      │
        │                 │ │                │ │                │
        │  Single script  │ │  Asset graph   │ │  DAG + tasks   │
        │  argparse CLI   │ │  Partitioned   │ │  Scheduled     │
        │  logging        │ │  Webserver UI  │ │  Webserver UI  │
        └─────────────────┘ └────────────────┘ └────────────────┘
```

## Summary Comparison

| Criteria | Option A (Pandas+Pydantic) | Option B (Dagster) | Option C (Airflow) |
|----------|---------------------------|--------------------|--------------------|
| **Migration effort** | Low | Medium | Medium-High |
| **Infrastructure needs** | None (just Python) | Dagster webserver | Airflow scheduler + DB + webserver |
| **Retry/error handling** | Manual (try/except) | Built-in RetryPolicy | Built-in retries per task |
| **Observability** | Logging only | Full UI with lineage | DAG UI with task logs |
| **Date partitioning** | Manual (argparse) | Native DailyPartitions | Native execution_date |
| **Backfill support** | Manual re-run | One-click backfill | CLI backfill command |
| **Idempotency** | Must implement manually | Asset-level materialization | Must implement manually |
| **Learning curve** | Minimal | Moderate | Moderate-High |
| **Scalability** | Single process | Worker pools | Celery/K8s executors |
| **Data lineage** | None | Full asset graph | Limited (task-level) |
| **Testing** | Standard pytest | Dagster testing utilities | Airflow test utilities |
| **Community/ecosystem** | N/A | Growing rapidly | Very large, mature |
| **Best for** | Quick wins, small team | Data-centric pipelines | Complex multi-system orchestration |

## Execution Model Comparison

```
OPTION A — Sequential Script
═══════════════════════════════════════════════════════════

  $ python -m modernized.option_a_pandas.trade_processor --date 20240315

  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
  │  Load    │──▶│ Validate │──▶│ Enrich   │──▶│ Reconcile│──▶│  Write   │
  │  CSV     │   │  Trades  │   │ (amounts │   │ (merge)  │   │  Output  │
  │          │   │          │   │  settle) │   │          │   │          │
  └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
       │                                             ▲
       │              ┌──────────┐                   │
       └─────────────▶│  Load    │───────────────────┘
                      │ Confirms │
                      └──────────┘


OPTION B — Dagster Asset Graph
═══════════════════════════════════════════════════════════

  $ dagster dev -m modernized.option_b_dagster.definitions

  ┌──────────────┐         ┌──────────────┐
  │  raw_trades  │────────▶│  validated   │──┐
  │  (@asset)    │         │  _trades     │  │   ┌──────────────┐   ┌──────────────┐
  └──────────────┘         └──────────────┘  ├──▶│  reconciled  │──▶│  (Output     │
                                             │   │  _trades     │   │   persisted) │
  ┌──────────────┐   ┌──────────────┐        │   └──────────────┘   └──────────────┘
  │  counterparty│──▶│  enriched    │────────┘
  │  _confirms   │   │  _trades     │
  └──────────────┘   └──────────────┘

  [Dagster UI: http://localhost:3000]
  - Full asset lineage graph
  - Partition-aware materialization
  - Built-in retry policies


OPTION C — Airflow DAG
═══════════════════════════════════════════════════════════

  Schedule: "30 6 * * 1-5" (6:30 AM weekdays)

  ┌──────────────┐         ┌──────────────┐   ┌──────────────┐
  │ load_trades  │────────▶│  validate    │──▶│   enrich     │──┐
  │ (Operator)   │         │  (Operator)  │   │  (Operator)  │  │
  └──────────────┘         └──────────────┘   └──────────────┘  │
                                                                │  ┌──────────────┐   ┌──────────────┐
  ┌──────────────┐                                              ├─▶│  reconcile   │──▶│ write_output │
  │load_confirms │──────────────────────────────────────────────┘  │  (Operator)  │   │  (Operator)  │
  │ (Operator)   │                                                 └──────────────┘   └──────────────┘
  └──────────────┘

  [Airflow UI: http://localhost:8080]
  - DAG visualization
  - Task-level logs & retries
  - XCom for inter-task data
```

## What Each Option Fixes

### Legacy Bugs → Modernization Fixes

| Legacy Bug | Option A | Option B | Option C |
|------------|----------|----------|----------|
| **Hardcoded Windows paths** | Config loader + argparse | ConfigurableResource | Airflow Variables/Connections |
| **Global mutable state** | Function args/returns | Asset inputs/outputs | XCom + task isolation |
| **No error handling** | try/except + logging | Built-in error capture + UI | Task retries + callbacks |
| **Broken T+2 settlement** | `calculate_t_plus_2()` (BDay) | Same (shared common) | Same (shared common) |
| **O(n²) reconciliation** | `pd.merge()` O(n) hash join | Same (shared common) | Same (shared common) |
| **csv.reader positional indexing** | `pd.read_csv()` with named cols | Same (shared common) | Same (shared common) |
| **print() instead of logging** | Python `logging` module | `context.log` (Dagster) | Python `logging` + task logs |
| **No data validation** | Pydantic model validation | Same + Dagster type checks | Same (shared common) |
| **File handle leaks (no `with`)** | `with` statements | pandas handles I/O | `with` statements |
| **Config file unused** | `load_config()` from INI | Resource-based config | Airflow Variables |
| **No dedup idempotency** | DataFrame `duplicated()` | Asset materialization | Must implement manually |

### What Each Option Doesn't Fix

| Limitation | Option A | Option B | Option C |
|------------|----------|----------|----------|
| **Holiday calendar for T+2** | Weekends only (noted) | Weekends only (noted) | Weekends only (noted) |
| **Database integration** | Not included | Resource placeholder | Connection placeholder |
| **Real-time processing** | Batch only | Batch (sensors possible) | Batch (sensors possible) |
| **Multi-file orchestration** | Single script | Single pipeline | Could extend DAG |
| **Alert/notification** | Log file only | Dagster alerts (add-on) | email_on_failure callback |

## Detailed Comparison

### Migration Effort

```
LOW ◀════════════════════════════════════════════▶ HIGH

  Option A          Option B              Option C
  ████░░░░░░        ██████░░░░            ████████░░
  ~1-2 days         ~3-5 days             ~5-7 days

  Just refactor     Learn Dagster         Set up Airflow infra
  the script        concepts, define      (scheduler, DB, webserver),
                    assets & resources    define DAG, operators, XCom
```

**Option A** is a straightforward refactoring exercise — same execution model (run a Python script), just cleaner code with proper abstractions.

**Option B** requires learning Dagster's asset model, resources, and partitioning concepts, but the code stays Pythonic and the common layer does the heavy lifting.

**Option C** requires the most infrastructure setup (Airflow needs a metadata database, scheduler process, and webserver) and understanding of Airflow's execution model (XCom, operators, connections).

### Observability

```
Option A:                        Option B:                       Option C:
┌─────────────────────┐         ┌─────────────────────────┐     ┌──────────────────────────┐
│ $ tail -f trade.log │         │ ┌─────────────────────┐ │     │ ┌──────────────────────┐ │
│                     │         │ │   DAGSTER UI         │ │     │ │   AIRFLOW UI          │ │
│ 2024-03-15 06:30:01 │         │ │                     │ │     │ │                      │ │
│ INFO: Loaded 15 trd │         │ │  raw_trades ──▶     │ │     │ │  ○──○──○──○──○──○    │ │
│ INFO: 1 duplicate   │         │ │  validated  ──▶     │ │     │ │  Task instances      │ │
│ INFO: 13 valid      │         │ │  enriched   ──▶     │ │     │ │  with logs, duration │ │
│ INFO: 10 matched    │         │ │  reconciled ──▶     │ │     │ │  retry count, etc.   │ │
│ WARNING: 3 unmatched│         │ │                     │ │     │ │                      │ │
│                     │         │ │  [Metadata panels]  │ │     │ │  [Gantt chart view]  │ │
│ (grep the log file) │         │ │  [Run history]      │ │     │ │  [Tree/Graph view]   │ │
└─────────────────────┘         │ │  [Partition status] │ │     │ │  [Code view]         │ │
                                │ └─────────────────────┘ │     │ └──────────────────────┘ │
 Text logs only.                │ Full lineage graph,     │     │ DAG visualization,       │
 No UI.                         │ run history, metadata.  │     │ task logs, Gantt charts.  │
                                └─────────────────────────┘     └──────────────────────────┘
```

### Backfill Capability

```
Option A:  Must write a bash loop
  $ for d in 20240101 20240102 ... 20240315; do
  $   python -m modernized.option_a_pandas.trade_processor --date $d
  $ done

Option B:  One-click in Dagster UI
  ┌─────────────────────────────────────────────┐
  │  Backfill partitions: [2024-01-01] to       │
  │  [2024-03-15]                               │
  │                          [Launch Backfill]   │
  └─────────────────────────────────────────────┘

Option C:  CLI command
  $ airflow dags backfill trade_processing \
      --start-date 2024-01-01 \
      --end-date 2024-03-15
```

### Scalability Path

```
Option A:                Option B:                    Option C:
┌────────────────┐      ┌────────────────────┐       ┌─────────────────────────┐
│  Single        │      │  Dagster+           │       │  Airflow + Celery       │
│  Process       │      │                    │       │                         │
│  ┌──┐          │      │  ┌──┐ ┌──┐ ┌──┐   │       │  ┌──┐ ┌──┐ ┌──┐ ┌──┐  │
│  │░░│          │      │  │░░│ │░░│ │░░│   │       │  │░░│ │░░│ │░░│ │░░│  │
│  └──┘          │      │  └──┘ └──┘ └──┘   │       │  └──┘ └──┘ └──┘ └──┘  │
│                │      │  Worker Pool       │       │  Celery Workers        │
│  No built-in   │      │                    │       │                         │
│  parallelism   │      │  Or Dagster Cloud  │       │  Or K8s Executor        │
└────────────────┘      └────────────────────┘       └─────────────────────────┘
```

## Recommendation

### Primary Recommendation: **Option B (Dagster)**

For Meridian Capital's use case — a data-centric investment pipeline processing daily batch files with reconciliation requirements — **Dagster is the strongest fit** for the following reasons:

1. **Asset-centric model aligns with financial data flows.** Each processing step (raw trades → validated → enriched → reconciled) naturally maps to a Dagster asset. The lineage graph gives the operations team instant visibility into data dependencies.

2. **Native date partitioning** matches the daily batch processing model. Backfilling missed dates is a one-click operation, critical for a firm that needs to reprocess historical data after fixing bugs.

3. **Built-in metadata and observability** replaces the "failures discovered when clients call" problem. Every asset materialization records row counts, error counts, and timing — queryable from the UI without grep-ing log files.

4. **Moderate migration effort with high payoff.** The common layer handles 80% of the logic. The Dagster-specific code is primarily orchestration, resource binding, and metadata emission — a few hundred lines of well-structured Python.

5. **Testing story is superior.** Dagster's `materialize_to_memory()` utility lets you unit test individual assets with mock inputs, something neither Option A nor Option C offers as cleanly.

### Incremental Migration Path

```
PHASE 1 (Week 1-2)         PHASE 2 (Week 3-4)         PHASE 3 (Month 2+)
════════════════════        ════════════════════        ════════════════════

  Deploy Option A             Deploy Option B            Full Dagster
  alongside legacy            for trade processing       for all 5 scripts

  ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
  │ Legacy runs at  │        │ Dagster handles  │        │ Dagster handles │
  │ 6:30 AM         │        │ trades + recon   │        │ all pipelines:  │
  │                 │        │                  │        │ - trades        │
  │ Option A runs   │        │ Legacy handles   │        │ - NAV calc      │
  │ in parallel for │        │ remaining 4      │        │ - recon         │
  │ validation      │        │ scripts          │        │ - compliance    │
  └─────────────────┘        └─────────────────┘        │ - reports       │
                                                         └─────────────────┘
  Verify identical           Retire legacy trade         Retire all legacy
  output                     processing                  scripts
```

If the team prefers a more conservative approach, **start with Option A** as a stepping stone. It can be deployed immediately with zero infrastructure changes, validated against the legacy output, and then the team can migrate to Option B once they're comfortable with the refactored logic.

Option C (Airflow) is best suited for organizations with **existing Airflow infrastructure** or teams that need to orchestrate across many heterogeneous systems (not just Python data pipelines). For a focused financial data pipeline like Meridian's, Dagster's asset model is more natural than Airflow's task-based DAG model.
