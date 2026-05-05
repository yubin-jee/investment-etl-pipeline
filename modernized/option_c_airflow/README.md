# Option C — Apache Airflow

## Overview

This implementation uses **Apache Airflow** to orchestrate the Meridian Capital
trade processing pipeline as a directed acyclic graph (DAG). Each processing
step is a discrete Airflow task backed by a `PythonOperator` that calls into
the shared common layer (`modernized/common/`).

### Pipeline DAG

```
load_trades >> validate_trades >> enrich_trades ──┐
                                                  ├──> reconcile >> write_output
load_confirms ────────────────────────────────────┘
```

| Task | Description |
|------|-------------|
| `load_trades` | Ingest the daily trade CSV via `common.parsers.load_trades_csv` |
| `validate_trades` | Validate against Pydantic models and broker whitelist |
| `enrich_trades` | Calculate gross/net amounts; fill missing settle dates (T+2) |
| `load_confirms` | Ingest counterparty confirmation file (parallel with above) |
| `reconcile` | Left-join trades with confirmations; classify MATCHED / BREAK / UNMATCHED |
| `write_output` | Write final reconciled CSV to `reports/` |

## Installation

```bash
pip install -r modernized/requirements_option_c.txt
```

Or install directly:

```bash
pip install apache-airflow pandas pydantic python-dotenv
```

## Local Airflow Setup

### 1. Set Airflow Home

```bash
export AIRFLOW_HOME=~/airflow
```

### 2. Initialize the Database

```bash
airflow db init
```

### 3. Create an Admin User

```bash
airflow users create \
    --username admin \
    --password admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com
```

### 4. Configure DAG Discovery

Add the repository's `modernized/option_c_airflow/dags/` directory to your
`airflow.cfg` or set the environment variable:

```bash
export AIRFLOW__CORE__DAGS_FOLDER=/path/to/investment-etl-pipeline/modernized/option_c_airflow/dags
```

Make sure the repo root is on `PYTHONPATH` so that the `modernized.*` imports
resolve:

```bash
export PYTHONPATH=/path/to/investment-etl-pipeline:$PYTHONPATH
```

### 5. Start the Scheduler and Webserver

```bash
# In separate terminals (or use tmux):
airflow scheduler &
airflow webserver --port 8080 &
```

Visit `http://localhost:8080` to access the Airflow UI.

## Triggering the DAG

### Automatic

The DAG is scheduled to run at **06:30 UTC, Monday–Friday**
(`30 6 * * 1-5`). Enable it in the Airflow UI or via CLI:

```bash
airflow dags unpause trade_processing
```

### Manual

```bash
airflow dags trigger trade_processing --exec-date 2024-03-15
```

Or click **Trigger DAG** in the Airflow web UI.

## Verifying the Setup

```bash
# Verify DAG parses correctly
cd /path/to/investment-etl-pipeline
python -c "from modernized.option_c_airflow.dags.trade_processing_dag import dag; print('DAG OK:', dag.dag_id)"

# Verify task imports
python -c "from modernized.option_c_airflow.tasks.trade_tasks import load_trades; print('Tasks OK')"
```

## Pros

- **Industry standard** — Apache Airflow is the most widely adopted workflow
  orchestrator in data engineering, with a massive community and ecosystem.
- **Built-in retries and scheduling** — Configurable retry policies, SLAs,
  email alerts, and cron-based scheduling out of the box.
- **DAG UI** — Rich web interface for monitoring runs, viewing logs, inspecting
  XCom values, and manually triggering / clearing tasks.
- **Scalable executors** — Celery, Kubernetes, and Dask executors allow
  horizontal scaling without code changes.
- **Extensibility** — Hundreds of provider packages for connecting to external
  systems (S3, GCS, Snowflake, Slack, etc.).

## Cons

- **Heavy infrastructure** — Requires a metadata database (Postgres/MySQL),
  a scheduler process, and a webserver. Not trivial to self-host in production.
- **Higher learning curve** — DAG authoring, XCom serialization, operator
  semantics, and executor configuration add complexity compared to a simple
  script.
- **XCom limitations for large data** — XCom stores task return values in the
  metadata DB by default. For large DataFrames, you must serialize to external
  storage (Parquet files, S3, etc.) and pass only file paths through XCom —
  which is what this implementation does.
- **Idempotency is manual** — Airflow does not enforce idempotent tasks;
  developers must design re-runnable tasks themselves (e.g., overwrite-on-write
  output strategy, deduplication logic).
- **Cold-start latency** — The scheduler polls for new DAG runs on an interval,
  which can introduce seconds to minutes of latency before a task actually
  starts executing.
