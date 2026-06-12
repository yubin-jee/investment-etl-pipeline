# Option C — Apache Airflow

This option expresses the legacy `legacy_scripts/process_trades.py` pipeline as
an **Apache Airflow DAG**. It is one of three parallel modernization prototypes;
all three are built on the same shared `modernized/common/` layer (Pydantic
models, pandas parsers, validation, T+2 settlement, config loader), so given the
same input they produce **identical** output. Only the *orchestration and
execution model* differs.

```
load CSV ─► validate ─► enrich (amounts + T+2) ─► load confirms ─► reconcile ─► write CSV
```

## Layout

```
option_c_airflow/
├── __init__.py
├── dags/
│   ├── __init__.py
│   └── trade_processing_dag.py   # the Airflow DAG (schedule, sensor, operators)
├── tasks/
│   ├── __init__.py
│   └── trade_tasks.py            # task callables built on modernized.common
├── verify_pipeline.py            # standalone harness (no scheduler needed)
└── README.md
```

## The DAG

`dags/trade_processing_dag.py` defines a DAG with `dag_id="trade_processing"`:

- **Schedule:** `schedule_interval="30 6 * * 1-5"` — 6:30 AM on weekdays,
  matching the legacy Windows Task Scheduler entry `trade_processing = 06:30`.
- **File gating:** a `FileSensor` (`wait_for_trade_file`) waits for the day's
  trade CSV to land before any processing starts (`mode="reschedule"` so it
  frees the worker slot between pokes).
- **Tasks:** six `PythonOperator`s — `load_trades`, `validate_trades`,
  `enrich_trades`, `load_confirms`, `reconcile`, `write_output` — each delegating
  to a callable in `tasks/trade_tasks.py`.
- **Reliability:** `retries=3`, `retry_delay=timedelta(minutes=5)`, and an
  `on_failure_callback` (`alert_on_failure`) that logs an alert (a stub for
  PagerDuty/Opsgenie/SMTP in production).
- **Dependencies (`>>`):**

  ```
  wait_for_trade_file ─► load_trades ─► validate_trades ─► enrich_trades ─┐
                              └─► load_confirms ──────────────────────────┴─► reconcile ─► write_output
  ```

  `load_confirms` runs in parallel with the validate/enrich branch; both feed
  `reconcile`.

### Passing data between tasks

Airflow runs each task in its own worker process, so in-memory DataFrames can't
simply be returned and reused downstream. We use two channels:

- **Staging pickle files for the bulk DataFrames.** Each stage writes its output
  DataFrame to a per-run staging directory keyed by the run's `ds`
  (`<tmp>/trade_processing/<ds>/<stage>.pkl`). Pickle is used rather than
  CSV/parquet because it preserves dtypes (`datetime64`, `Int64`) exactly and
  needs no extra dependency.
- **XCom for the small summary stats.** Every task *returns* a small dict of
  scalar counts (`total_loaded`, `matched`, …); Airflow pushes these to XCom,
  the recommended channel for small metadata.

### Spec-named composite callables

In addition to the six per-stage callables, `trade_tasks.py` exposes the four
composite callables named in the spec — `load_and_validate_trades`,
`enrich_trades`, `load_and_reconcile`, `write_results` — each
`(execution_date, config_path) -> dict`. They compose the per-stage callables and
make the pipeline easy to test directly without a running scheduler. All
callables also accept `**kwargs`, so they work unchanged as Airflow
`PythonOperator` callables (which inject the task context, including `ds` /
`execution_date`).

### File resolution

Inputs are resolved from `config/batch_config.ini` first, then fall back to the
committed data. The legacy `.ini` stores Windows network-drive paths
(`C:\MeridianData\...`) that don't exist on this host, so the resolver detects
and skips Windows-style paths and falls back to `legacy_data/trades/` and then
`modernized/test_data/`. Confirmations are looked up alongside the resolved trade
file so trades and confirms come from the same dataset. Output is written to the
configured `report_output` when usable, otherwise to `option_c_airflow/output/`.

## Setup

Python 3.12 with `pandas` and `pydantic` installed (see the repo root). Install
this option's extra dependencies from the existing requirements file:

```bash
pip install -r modernized/requirements_option_c.txt
```

> Apache Airflow is heavy. If a full Airflow install isn't practical, you can
> still verify the underlying business logic with the standalone harness (see
> "Verify the callables" below) — it needs only `pandas` + `pydantic`.

## How to run

Run everything from the **repo root** so the `modernized` package resolves
(it uses absolute imports `modernized.common.*`).

### Verify the callables (no Airflow scheduler required)

```bash
python -m modernized.option_c_airflow.verify_pipeline
```

Expected final line:

```
SUMMARY: total_loaded=7 duplicates_removed=1 validation_errors=2 matched=1 breaks=2 unmatched=1
```

This writes `modernized/option_c_airflow/output/trade_report_20240115.csv` and
`trade_errors_20240115.csv`.

### Run the full DAG with Airflow

```bash
# 1. Point Airflow at a home dir and this dags folder; sqlite + SequentialExecutor is fine for a test.
export AIRFLOW_HOME=/tmp/airflow_home
export PYTHONPATH=$PWD                                   # so `modernized` imports resolve
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__EXECUTOR=SequentialExecutor
export AIRFLOW__CORE__DAGS_FOLDER=$PWD/modernized/option_c_airflow/dags

# 2. Initialize the metadata DB.
airflow db migrate

# 3. The FileSensor needs an `fs_default` connection (created once).
airflow connections add fs_default --conn-type fs --conn-extra '{"path": "/"}'

# 4. Run the whole DAG for a logical date (uses the committed test data).
airflow dags test trade_processing 2024-01-15
```

All tasks complete with state `success`; `write_output` logs the summary
`{'total_loaded': 7, 'duplicates_removed': 1, 'validation_errors': 2,
'matched': 1, 'breaks': 2, 'unmatched': 1}`.

You can also exercise a single task:

```bash
airflow tasks test trade_processing reconcile 2024-01-15
```

## Pros / cons

**Pros**

- **Very large ecosystem** — operators/hooks for almost every system, huge
  community, mature tooling.
- **Built-in scheduling, retries, backfills** — `schedule_interval`,
  `execution_date`/`ds` partitioning, CLI backfills, per-task retries with
  delay.
- **Operational visibility** — the web UI shows DAG/task status, logs, and
  history; alerting via `on_failure_callback`.
- **Multi-system orchestration** — strong fit when the pipeline must coordinate
  many external systems (DBs, file shares, APIs).

**Cons**

- **Heavy infrastructure** — needs a scheduler, a metadata database, and
  (for production) a webserver and an executor (Celery/Kubernetes).
- **Inter-task data passing is manual** — no native asset graph; bulk data goes
  through staging files / XCom (as done here), and idempotency must be
  implemented by hand.
- **Limited data lineage** — task-level only, versus an asset-graph tool.
- **Moderate–high learning curve** and more operational overhead than a single
  script (Option A).
```
