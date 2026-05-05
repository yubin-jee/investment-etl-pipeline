# Trade Processing Modernization — Option Comparison

This document provides a side-by-side comparison of three modernization
approaches for the Meridian Capital trade processing pipeline. All three
options replace `legacy_scripts/process_trades.py` and share the same
common layer (`modernized/common/`), differing only in orchestration and
execution model.

---

## Architecture Overview

```
                         ┌─────────────────────────────┐
                         │      modernized/common/      │
                         │  models · parsers · validation│
                         │  settlement · config          │
                         └──────────┬──────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
   ┌──────────▼──────────┐ ┌───────▼──────────┐ ┌────────▼─────────┐
   │   Option A          │ │   Option B       │ │   Option C       │
   │   Pandas + Pydantic │ │   Dagster        │ │   Airflow        │
   │                     │ │                  │ │                  │
   │  Single script      │ │  Asset graph     │ │  DAG + operators │
   │  argparse CLI       │ │  Webserver UI    │ │  Scheduler + UI  │
   │  logging module     │ │  Retry policies  │ │  XCom data pass  │
   └─────────────────────┘ └──────────────────┘ └──────────────────┘
```

### Execution Flow Comparison

**Option A — Linear Script**
```
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  Load    │───▶│ Validate │───▶│ Enrich   │───▶│  Load    │───▶│  Recon   │───▶│  Write   │
  │  Trades  │    │  Trades  │    │  Trades  │    │ Confirms │    │  cile    │    │  Output  │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
  Sequential execution — simple, but no parallelism or retry
```

**Option B — Dagster Asset Graph**
```
  ┌──────────────┐
  │  raw_trades  │──────┐
  └──────────────┘      │
                        ▼
              ┌──────────────────┐
              │ validated_trades │
              └──────────────────┘
                        │
                        ▼
              ┌──────────────────┐     ┌───────────────────────┐
              │ enriched_trades  │     │ counterparty_confirms │
              └────────┬─────────┘     └──────────┬────────────┘
                       │                          │
                       └──────────┬───────────────┘
                                  ▼
                       ┌───────────────────┐
                       │ reconciled_trades │
                       └───────────────────┘
  Asset-level lineage — Dagster auto-tracks dependencies
```

**Option C — Airflow DAG**
```
  load_trades ──▶ validate_trades ──▶ enrich_trades ──┐
                                                       ├──▶ reconcile ──▶ write_output
  load_confirms ─────────────────────────────────────┘
  Task-level parallelism — load_confirms runs independently
```

---

## Summary Comparison

| Criteria                 | Option A (Pandas + Pydantic) | Option B (Dagster)                | Option C (Airflow)                     |
|--------------------------|------------------------------|-----------------------------------|----------------------------------------|
| **Migration effort**     | Low                          | Medium                            | Medium-High                            |
| **Infrastructure needs** | None (just Python)           | Dagster webserver                 | Airflow scheduler + DB + webserver     |
| **Retry/error handling** | Manual (`try`/`except`)      | Built-in `RetryPolicy`           | Built-in retries per task              |
| **Observability**        | Logging only                 | Full UI with asset lineage        | DAG UI with task logs                  |
| **Date partitioning**    | Manual (`argparse`)          | Native `DailyPartitionsDefinition`| Native `execution_date`                |
| **Backfill support**     | Manual re-run with `--date`  | One-click backfill in UI          | CLI `airflow backfill` command         |
| **Idempotency**          | Must implement manually      | Asset-level materialization       | Must implement manually                |
| **Learning curve**       | Minimal                      | Moderate                          | Moderate-High                          |
| **Scalability**          | Single process               | Worker pools                      | Celery/K8s executors                   |
| **Data lineage**         | None                         | Full asset graph                  | Limited (task-level only)              |
| **Testing**              | Standard `pytest`            | Dagster testing utilities         | Airflow test utilities                 |
| **Community/ecosystem**  | N/A                          | Growing rapidly                   | Very large, mature                     |
| **Best for**             | Quick wins, small team       | Data-centric pipelines            | Complex multi-system orchestration     |

---

## What Each Option Fixes

### Legacy Bug: Global Mutable State

| Bug / Debt Item                 | Option A                       | Option B                         | Option C                          |
|---------------------------------|--------------------------------|----------------------------------|-----------------------------------|
| Global variables                | Function args/returns only     | Asset inputs/outputs             | XCom + task callables             |
| Hardcoded Windows paths         | Config loader + CLI args       | `ConfigurableResource`           | Airflow Variables / Connections   |
| Broken T+2 settlement           | `common.settlement` (BDay)    | `common.settlement` (BDay)      | `common.settlement` (BDay)       |
| No error handling               | `try`/`except` + logging      | Built-in error tracking          | Task retries + callbacks          |
| `print()` instead of logging   | Python `logging` module        | `context.log`                    | Airflow task logger               |
| File handle leaks (no `with`)  | Context managers               | Handled by common layer          | Handled by common layer           |
| O(n²) reconciliation           | `pd.merge` hash join — O(n)   | `pd.merge` hash join — O(n)     | `pd.merge` hash join — O(n)      |
| Positional CSV indexing         | `pd.read_csv` with names      | `pd.read_csv` with names        | `pd.read_csv` with names         |
| Manual fixed-width parsing      | `pd.read_fwf` with colspecs   | `pd.read_fwf` with colspecs    | `pd.read_fwf` with colspecs     |
| No duplicate detection across runs | Dedup on `trade_id`        | Asset materialization records    | Dedup on `trade_id` + idempotent |
| Config file unused              | `configparser` loader          | Dagster resource config          | Airflow Variables                 |
| No data validation framework    | Pydantic v2 models             | Pydantic v2 models              | Pydantic v2 models               |

### Legacy Bug: Broken Settlement Date Calculation

The legacy code adds 2 calendar days and uses a rough "if day > 30" heuristic:

```python
# LEGACY (BROKEN)
day = int(parts[1]) + 2
if day > 30:
    day = day - 30
    month = month + 1
```

All three options fix this with `pd.tseries.offsets.BDay(2)`:

```python
# MODERNIZED (CORRECT)
from modernized.common.settlement import calculate_t_plus_2
settle_date = calculate_t_plus_2(trade_date)
# Friday 03/15/2024 → Tuesday 03/19/2024 (skips weekend)
```

---

## What Each Option Does NOT Fix

| Limitation                              | Option A | Option B | Option C |
|-----------------------------------------|----------|----------|----------|
| Holiday calendar for settlement         | No*      | No*      | No*      |
| Database integration (SQL Server)       | No       | Possible via resources | Possible via hooks |
| Real-time trade processing              | No       | No (batch-oriented)    | No (batch-oriented) |
| Cross-run dedup (idempotent across days)| Partial  | Yes (asset materialization) | Partial |
| Email/Slack alerting on failures        | No       | Possible via sensors   | Yes (callbacks + operators) |
| Multi-file/multi-day batch processing   | Manual loop | Native partitioning | Native scheduling |

\* All options include a note about integrating `exchange_calendars` or `pandas.tseries.holiday` for future enhancement.

---

## Detailed Pros & Cons

### Option A: Pandas + Pydantic

```
  ┌─────────────────────────────────────────────────┐
  │                  OPTION A                        │
  │           Pandas + Pydantic Script               │
  │                                                  │
  │  ┌────────┐    "Just a Python script"            │
  │  │ python │──▶  argparse --date --config         │
  │  └────────┘    Single process, exit code 0/1     │
  │                                                  │
  │  STRENGTHS           │  WEAKNESSES               │
  │  ✦ Zero infra        │  ✦ No retry logic         │
  │  ✦ Easy to debug     │  ✦ No scheduling          │
  │  ✦ Fast to migrate   │  ✦ No observability UI    │
  │  ✦ Team knows it     │  ✦ Manual backfills       │
  └─────────────────────────────────────────────────┘
```

**Best suited for:** Teams that want an incremental first step — clean up
the code quality without introducing new infrastructure.

### Option B: Dagster

```
  ┌─────────────────────────────────────────────────┐
  │                  OPTION B                        │
  │              Dagster Assets                      │
  │                                                  │
  │  ┌──────────────────────────────────────┐        │
  │  │         Dagster Webserver UI          │        │
  │  │  ┌─────┐  ┌─────┐  ┌─────┐          │        │
  │  │  │Asset│─▶│Asset│─▶│Asset│  Lineage  │        │
  │  │  └─────┘  └─────┘  └─────┘  Graph    │        │
  │  └──────────────────────────────────────┘        │
  │                                                  │
  │  STRENGTHS            │  WEAKNESSES              │
  │  ✦ Full asset lineage │  ✦ Newer ecosystem       │
  │  ✦ Built-in retry     │  ✦ Dagster webserver req │
  │  ✦ One-click backfill │  ✦ Moderate learning     │
  │  ✦ Great testing      │  ✦ Smaller community     │
  │  ✦ Data-centric model │                          │
  └─────────────────────────────────────────────────┘
```

**Best suited for:** Data engineering teams building data-centric
pipelines where asset lineage and observability are high priorities.

### Option C: Airflow

```
  ┌─────────────────────────────────────────────────┐
  │                  OPTION C                        │
  │              Airflow DAG                         │
  │                                                  │
  │  ┌──────────────────────────────────────┐        │
  │  │  Scheduler │ Webserver │ Metadata DB │        │
  │  │  ┌────┐  ┌────┐  ┌────┐  ┌────┐     │        │
  │  │  │Task│─▶│Task│─▶│Task│─▶│Task│     │        │
  │  │  └────┘  └────┘  └────┘  └────┘     │        │
  │  └──────────────────────────────────────┘        │
  │                                                  │
  │  STRENGTHS            │  WEAKNESSES              │
  │  ✦ Battle-tested      │  ✦ Heavy infrastructure  │
  │  ✦ Huge community     │  ✦ XCom data limits      │
  │  ✦ Rich operator lib  │  ✦ Task-level lineage    │
  │  ✦ Native scheduling  │  ✦ Steeper learning      │
  │  ✦ K8s/Celery scaling │  ✦ Complex setup         │
  └─────────────────────────────────────────────────┘
```

**Best suited for:** Organizations with complex, multi-system orchestration
needs and existing Airflow expertise or infrastructure.

---

## Migration Path Recommendation

### Primary Recommendation: Option B (Dagster)

For Meridian Capital's use case — a data-centric investment pipeline
processing daily trade files — **Dagster is the recommended approach**
for the following reasons:

1. **Asset-centric model** aligns naturally with financial data flows
   (trades → validated trades → enriched trades → reconciled trades)
2. **Built-in data lineage** addresses the "no data lineage" technical
   debt item from the legacy system
3. **Native partitioning** by date is a perfect fit for daily batch
   processing
4. **Retry policies** at the asset level handle transient failures
   without custom code
5. **Testing utilities** (`build_asset_context`, `materialize_to_memory`)
   make it straightforward to write unit/integration tests
6. **Lower infrastructure burden** than Airflow — a single
   `dagster dev` command gets you a working webserver

### Stepping Stone: Option A First

If the team wants to move incrementally:

```
  Phase 1 (Week 1-2)          Phase 2 (Week 3-6)
  ┌──────────────────┐        ┌──────────────────────┐
  │   Deploy Option A │───────▶│   Migrate to Option B │
  │   (drop-in replace │        │   (wrap with Dagster   │
  │    for legacy)     │        │    assets)             │
  └──────────────────┘        └──────────────────────┘
```

1. **Phase 1:** Deploy Option A as a direct replacement for the legacy
   script. Same scheduling (cron/Task Scheduler), same I/O, but with
   clean code, proper validation, and correct settlement dates.

2. **Phase 2:** Wrap the Option A logic in Dagster assets. The common
   layer makes this straightforward — the processing logic stays the
   same, only the orchestration changes.

### When to Choose Airflow Instead

Option C (Airflow) is the better choice if:
- The team already has Airflow infrastructure and expertise
- The pipeline needs to orchestrate non-Python systems (Spark, dbt, cloud services)
- Complex scheduling with multiple interdependent DAGs is required
- The organization has a platform team that manages Airflow

---

## Running the Comparison

All three options can be tested against the same sample data:

```bash
# Option A: Direct script execution
python -m modernized.option_a_pandas.trade_processor --date 20240315

# Option B: Dagster materialization
dagster dev -m modernized.option_b_dagster.definitions
# Then materialize assets in the Dagster UI at http://localhost:3000

# Option C: Airflow DAG
export AIRFLOW_HOME=~/airflow
airflow db init
airflow dags test trade_processing 2024-03-15
```

All three should produce identical output CSV files in the `reports/`
directory, allowing direct comparison against the legacy script's output.
