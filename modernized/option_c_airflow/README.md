# Option C: Apache Airflow DAG-based Trade Processing

## Overview

This option wraps the shared common layer (`modernized/common/`) with
**Apache Airflow** — the industry-standard workflow orchestrator. Trades
are processed through a Directed Acyclic Graph (DAG) where each step is
an independent, retryable Airflow task. Airflow's scheduler handles
cron-based triggering, and its web UI provides full visibility into run
history, task logs, and dependency graphs.

## Task Dependency Diagram

```
load_trades ──> validate_trades ──> enrich_trades ──┐
                                                     ├──> reconcile ──> write_output
load_confirms ──────────────────────────────────────┘
```

- **load_trades** – Reads the daily CSV trade file via `common.parsers`.
- **validate_trades** – Deduplicates and validates rows using Pydantic models.
- **enrich_trades** – Calculates gross/net amounts and fixes missing settlement dates.
- **load_confirms** – Parses fixed-width counterparty confirmation files (runs in parallel).
- **reconcile** – Merges trades with confirms and flags MATCHED / PRICE_BREAK / QTY_BREAK / UNMATCHED.
- **write_output** – Writes the final report CSV and an error log (if any).

## Installation

```bash
pip install -r modernized/requirements_option_c.txt
```

## Airflow Setup

### 1. Initialize the metadata database

```bash
export AIRFLOW_HOME=~/airflow
airflow db init
```

### 2. Create an admin user

```bash
airflow users create \
    --username admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@meridian.example \
    --password admin
```

### 3. Point Airflow at this DAG folder

Edit `$AIRFLOW_HOME/airflow.cfg`:

```ini
[core]
dags_folder = /path/to/investment-etl-pipeline/modernized/option_c_airflow/dags
```

Or set the environment variable:

```bash
export AIRFLOW__CORE__DAGS_FOLDER=/path/to/investment-etl-pipeline/modernized/option_c_airflow/dags
```

## Running

### Quick start (development)

```bash
airflow standalone
```

This starts the webserver, scheduler, and triggerer in a single process.
Open [http://localhost:8080](http://localhost:8080) to view the DAG.

### Production (separate processes)

```bash
# Terminal 1
airflow webserver --port 8080

# Terminal 2
airflow scheduler
```

### Trigger a manual run

```bash
airflow dags trigger trade_processing --conf '{}'
```

## Pros

- **Mature ecosystem** — battle-tested in production at thousands of companies.
- **Strong community** — extensive documentation, Stack Overflow coverage, and active development.
- **Rich web UI** — built-in monitoring, log viewer, Gantt charts, and task-instance detail pages.
- **Native scheduling** — cron expressions, timetables, data-aware scheduling, and backfill support.
- **Extensive operator library** — 1 000+ pre-built operators for databases, cloud services, and APIs.
- **Battle-tested in production** — proven at scale with features like task retries, SLAs, and alerting.

## Cons

- **Heavier infrastructure** — requires a metadata database (Postgres/MySQL), a scheduler process, and a webserver.
- **Higher learning curve** — DAG authoring, XCom semantics, executor selection, and connection management add complexity.
- **XCom limitations for large data** — the default XCom backend stores data in the metadata DB; large DataFrames should use an external store (S3, GCS) instead.
- **Task-level lineage only** — Airflow tracks task dependencies, not column-level or row-level data lineage.
