# Option C: Apache Airflow DAG Pipeline

## Approach

Uses Apache Airflow to orchestrate trade processing as a DAG (Directed Acyclic Graph) of tasks, with built-in scheduling, retries, and task-level monitoring.

```
┌─────────────────────────────────────────────────────────────────┐
│               Airflow DAG (Option C)                            │
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │  wait_for_trade_file│   (FileSensor — waits for CSV)         │
│  │    poke_interval=60 │                                        │
│  └──────────┬──────────┘                                        │
│             ▼                                                   │
│  ┌─────────────────────┐                                        │
│  │load_and_validate    │   (PythonOperator)                     │
│  │  trades             │   Load CSV + Pydantic validation       │
│  └──────────┬──────────┘                                        │
│             ▼                                                   │
│  ┌─────────────────────┐                                        │
│  │  enrich_trades      │   (PythonOperator)                     │
│  │                     │   Amounts + T+2 settlement             │
│  └──────────┬──────────┘                                        │
│             ▼                                                   │
│  ┌─────────────────────┐                                        │
│  │load_and_reconcile   │   (PythonOperator)                     │
│  │                     │   Counterparty merge + break detection │
│  └──────────┬──────────┘                                        │
│             ▼                                                   │
│  ┌─────────────────────┐                                        │
│  │  write_results      │   (PythonOperator)                     │
│  │                     │   Final CSV output                     │
│  └─────────────────────┘                                        │
│                                                                 │
│  Schedule: "30 6 * * 1-5" (6:30 AM weekdays)                    │
│  Retries:  3 per task, 5-min delay                              │
│  Timeout:  1 hour per task                                      │
└─────────────────────────────────────────────────────────────────┘
```

## Key Improvements over Legacy

| Legacy Issue | How Airflow Fixes It |
|---|---|
| No retry logic | Built-in `retries=3, retry_delay=5min` per task |
| No file waiting | `FileSensor` waits for trade file before starting |
| No scheduling | Native cron-based scheduling (`schedule_interval`) |
| No alerting | `on_failure_callback` for Slack/PagerDuty/email |
| No observability | Airflow UI with task logs, duration, and history |
| Sequential execution | Task graph with parallelizable branches |
| No backfill | `airflow dags backfill` CLI command |
| Hardcoded paths | Config-driven via `batch_config.ini` |

## How to Run

### Local Development

```bash
# Install dependencies
pip install -r modernized/requirements_option_c.txt

# Initialize the Airflow database
export AIRFLOW_HOME=$(pwd)/airflow_home
airflow db init

# Create an admin user
airflow users create \
    --username admin \
    --password admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com

# Copy DAGs to Airflow's dags folder
mkdir -p $AIRFLOW_HOME/dags
cp modernized/option_c_airflow/dags/trade_processing_dag.py $AIRFLOW_HOME/dags/

# Start the Airflow webserver and scheduler (in separate terminals)
airflow webserver --port 8080
airflow scheduler
```

### Running a DAG

1. Open the Airflow UI at `http://localhost:8080`
2. Enable the `trade_processing` DAG
3. Trigger a manual run or wait for the schedule

### Backfill

```bash
airflow dags backfill trade_processing \
    --start-date 2024-01-15 \
    --end-date 2024-03-15
```

## Pros

- **Mature ecosystem** — largest orchestration community, battle-tested at scale
- **Built-in scheduling** — native cron-based DAG scheduling
- **File sensors** — waits for input files before processing
- **Rich UI** — task logs, Gantt charts, tree/graph views
- **Backfill support** — CLI and UI-based backfill
- **Alerting** — configurable failure callbacks
- **Scalable** — Celery and Kubernetes executors for production
- **Extensive integrations** — operators/hooks for AWS, GCP, databases, etc.

## Cons

- **Heavy infrastructure** — requires webserver, scheduler, and metadata database
- **Complex setup** — more operational overhead than Options A or B
- **Task-level lineage only** — no column-level or asset-level lineage
- **XCom limitations** — not designed for large data passing between tasks
- **DAG bag parsing** — can be slow with many DAGs
- **Steeper learning curve** — many concepts (operators, sensors, hooks, XCom, pools)
- **Idempotency not automatic** — must implement manually in task logic
