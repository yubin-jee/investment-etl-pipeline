# Trade Processing Modernization — Side-by-Side Comparison

> **Purpose**: Evaluate three approaches to replacing `legacy_scripts/process_trades.py`
> so the team can make an informed migration decision.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SHARED COMMON LAYER                                │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐    │
│  │ models.py│ │parsers.py│ │validation. │ │settlement. │ │ config.py│    │
│  │ Pydantic │ │  Pandas  │ │    py      │ │    py      │ │ConfigPars│    │
│  │ v2 models│ │CSV + FWF │ │Dedup+Valid │ │T+2 BDay    │ │INI loader│    │
│  └──────────┘ └──────────┘ └────────────┘ └────────────┘ └──────────┘    │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
│  OPTION A       │ │ OPTION B    │ │  OPTION C        │
│  Pandas+Pydantic│ │ Dagster     │ │  Airflow         │
│                 │ │             │ │                   │
│  Single script  │ │ Asset graph │ │  DAG + Operators  │
│  argparse CLI   │ │ Web UI      │ │  Scheduler + UI   │
│  logging module │ │ Partitions  │ │  XCom data pass   │
│  No infra       │ │ Retry policy│ │  Sensors + Retries│
└─────────────────┘ └─────────────┘ └─────────────────┘
```

---

## Summary Comparison

| Criteria | Option A (Pandas+Pydantic) | Option B (Dagster) | Option C (Airflow) |
|---|---|---|---|
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
| **Community/ecosystem** | N/A | Growing | Very large |
| **Best for** | Quick wins, small team | Data-centric pipelines | Complex multi-system orchestration |

---

## Execution Model Comparison

```
OPTION A — Linear Script
─────────────────────────
  ┌──────┐   ┌──────────┐   ┌────────┐   ┌───────┐   ┌───────┐   ┌────────┐
  │ Load │──▶│ Validate │──▶│ Enrich │──▶│ Load  │──▶│Recon- │──▶│ Write  │
  │ CSV  │   │ Trades   │   │ Trades │   │Confirms│  │ cile  │   │ Output │
  └──────┘   └──────────┘   └────────┘   └───────┘   └───────┘   └────────┘
  All in one Python process — simple but no parallelism or fault isolation


OPTION B — Dagster Asset Graph
──────────────────────────────
  ┌────────────────┐          ┌─────────────────────┐
  │  raw_trades    │          │ counterparty_       │
  │  (partitioned) │          │ confirms            │
  └───────┬────────┘          └──────────┬──────────┘
          │                              │
          ▼                              │
  ┌────────────────┐                     │
  │ validated_     │                     │
  │ trades         │                     │
  └───────┬────────┘                     │
          │                              │
          ▼                              │
  ┌────────────────┐                     │
  │ enriched_      │                     │
  │ trades         │                     │
  └───────┬────────┘                     │
          │              ┌───────────────┘
          ▼              ▼
  ┌────────────────────────┐
  │   reconciled_trades    │
  │ (merge + break detect) │
  └────────────────────────┘
  Each asset is independently materializable with full metadata


OPTION C — Airflow DAG
──────────────────────
  ┌─────────────┐
  │ FileSensor  │  (waits for trade file)
  └──────┬──────┘
         ▼
  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │   load_     │──▶│   enrich_   │──▶│    load_    │──▶│   write_    │
  │  validate   │   │   trades    │   │  reconcile  │   │  results    │
  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
         │                                                      │
         └──────────── XCom (temp file paths) ─────────────────┘
  Task-level retries, failure callbacks, scheduler-managed execution
```

---

## What Each Option Fixes

| Legacy Bug / Issue | Option A | Option B | Option C |
|---|---|---|---|
| **Hardcoded Windows paths** | Config-driven via `batch_config.ini` | Config via `TradeFileResource` | Config via Airflow Variables / env vars |
| **Global mutable state** | All data passed as function args/returns | Each asset is a pure function | Each task is an isolated callable |
| **No error handling** | try/except with logging | Built-in `RetryPolicy` + error metadata | `retries=3` + `on_failure_callback` |
| **print() instead of logging** | Python `logging` module | `context.log.info()` (Dagster) | Airflow task logger |
| **Broken T+2 settlement** | `calculate_t_plus_2()` using `BDay(2)` | Same (shared common layer) | Same (shared common layer) |
| **O(n²) reconciliation** | `pd.merge()` — O(n) hash join | Same (shared common layer) | Same (shared common layer) |
| **Positional CSV indexing** | `pd.read_csv()` with named columns | Same (shared common layer) | Same (shared common layer) |
| **No data validation** | Pydantic v2 model validation | Same (shared common layer) | Same (shared common layer) |
| **Fragile dedup** | `df.duplicated(subset=['trade_id'])` | Same (shared common layer) | Same (shared common layer) |
| **Config file unused** | `load_config()` reads INI | Same + Dagster resource config | Same + Airflow Variables |
| **No file existence check** | `Path.exists()` checks | Dagster I/O + error handling | `FileSensor` waits for file |
| **Unclosed file handles** | `with` statements | Pandas handles via common layer | Pandas handles via common layer |

---

## What Each Option Doesn't Fix

| Limitation | Option A | Option B | Option C |
|---|---|---|---|
| **Holiday calendar for T+2** | Weekend-only (noted for future) | Same | Same |
| **Database integration** | Still writes CSV (no DB) | Could add I/O managers | Could add DB operators |
| **Real-time processing** | Batch only | Batch (sensors possible) | Batch (sensors possible) |
| **Multi-file orchestration** | Single script handles one file | Can compose assets | Can add upstream DAGs |
| **Secrets management** | python-dotenv | Dagster secrets | Airflow Connections |
| **Horizontal scaling** | Single process | Needs Dagster Cloud / k8s | Needs Celery/K8s executor |

---

## Infrastructure Requirements

```
OPTION A                OPTION B                    OPTION C
────────                ────────                    ────────
┌──────────┐            ┌──────────────────┐        ┌──────────────────────┐
│  Python  │            │  Python          │        │  Python              │
│  3.9+    │            │  3.9+            │        │  3.9+                │
│          │            │                  │        │                      │
│  pandas  │            │  pandas          │        │  pandas              │
│  pydantic│            │  pydantic        │        │  pydantic            │
│          │            │  dagster         │        │  apache-airflow      │
│          │            │  dagster-websvr  │        │                      │
│          │            │                  │        │  ┌──────────────┐    │
│          │            │  ┌────────────┐  │        │  │ PostgreSQL / │    │
│          │            │  │ Dagster UI │  │        │  │ MySQL (meta) │    │
│          │            │  │ :3000      │  │        │  └──────────────┘    │
│          │            │  └────────────┘  │        │  ┌──────────────┐    │
│          │            │                  │        │  │ Scheduler    │    │
│          │            │                  │        │  │ Webserver    │    │
│          │            │                  │        │  │ Workers      │    │
│          │            │                  │        │  └──────────────┘    │
└──────────┘            └──────────────────┘        └──────────────────────┘
 ~3 pip pkgs             ~5 pip pkgs                 ~50+ transitive deps
 0 services              1 service                   3+ services
```

---

## Migration Path Comparison

```
                    COMPLEXITY
                        ▲
                        │
                    High│              ┌─────────┐
                        │              │Option C  │
                        │              │Airflow   │
                        │              └─────────┘
                        │
                 Medium │    ┌─────────┐
                        │    │Option B  │
                        │    │Dagster   │
                        │    └─────────┘
                        │
                    Low │ ┌─────────┐
                        │ │Option A  │
                        │ │Pandas   │
                        │ └─────────┘
                        │
                        └──────────────────────────────────▶
                          Low       Medium       High
                                 CAPABILITY
```

### Recommended Migration Path

```
  TODAY           PHASE 1            PHASE 2              PHASE 3
  ─────           ───────            ───────              ───────
  Legacy    ──▶   Option A     ──▶   Option B       ──▶   Option B
  Scripts         (quick win)        (full platform)       (production)

  • Week 1-2      • Week 3-6          • Week 7+
  • Validate       • Build asset       • Add monitoring
    common layer     graph              • Holiday calendars
  • Team learns   • Set up Dagster     • DB I/O managers
    new patterns     infrastructure    • CI/CD integration
```

---

## Recommendation

**Primary: Option B (Dagster)** for Meridian's use case.

### Why Dagster?

1. **Asset-centric model** maps naturally to financial data pipelines — trades, positions,
   and reconciliation results are assets with clear lineage.

2. **Native partitioning** by date eliminates manual date handling and enables one-click
   backfills for missed trading days.

3. **Built-in observability** — the Dagster UI shows the full asset graph, materialization
   history, and metadata (row counts, error counts) without additional tooling.

4. **Right-sized infrastructure** — unlike Airflow, Dagster doesn't require a separate
   database and scheduler daemon for development. `dagster dev` is a single command.

5. **Growing ecosystem** with first-class support for pandas, Pydantic, and data quality
   checks via `dagster-dbt` and asset checks.

### Stepping Stone: Option A First

If the team wants to move incrementally:

1. **Deploy Option A immediately** — it's a drop-in replacement for the legacy script
   with zero infrastructure changes. Same cron job, same file-based I/O.

2. **Migrate to Option B** once the team is comfortable with the common layer and wants
   automated scheduling, backfills, and lineage.

### When to Choose Option C (Airflow)

Option C makes sense if:
- Meridian already has Airflow infrastructure in place
- The pipeline will grow to orchestrate non-Python systems (Spark, dbt, external APIs)
- The ops team is already trained on Airflow

For a ~$2M AUM firm with 6 accounts and ~15 trades/day, Airflow's operational overhead
is disproportionate to the workload.
