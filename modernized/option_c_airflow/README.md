# Option C: Airflow DAG-Based Trade Processor

## How It Works

This module uses **Apache Airflow** for DAG-based task orchestration of the
daily trade processing pipeline. The workflow is defined as a Directed Acyclic
Graph (DAG) with four sequential tasks:

1. **load_validate** — Load the daily trade CSV, deduplicate, validate each
   record against Pydantic models, and persist valid trades.
2. **enrich** — Calculate gross/net amounts, apply commissions (add for BUY,
   subtract for SELL), and fill missing settlement dates using T+2 business
   day logic.
3. **load_reconcile** — Load counterparty confirmation files (fixed-width),
   merge with enriched trades, and classify each as MATCHED, PRICE_BREAK,
   QTY_BREAK, or UNMATCHED.
4. **write_output** — Write the final reconciled output CSV and a consolidated
   error log.

Data is passed between tasks via **XCom** (temp file paths). All business
logic is delegated to the shared `modernized/common/` layer.

## Setup

```bash
# Install dependencies
pip install -r modernized/requirements_option_c.txt

# Initialize Airflow (local dev)
export AIRFLOW_HOME=./airflow_home
airflow db init

# Verify the DAG is detected
airflow dags list
```

## Triggering a Run

```bash
# Manual trigger
airflow dags trigger trade_processing

# Or run with a specific date
airflow dags trigger trade_processing --conf '{"base_dir": "modernized/test_data"}'
```

## DAG Schedule

| Field    | Value               |
|----------|---------------------|
| Cron     | `30 6 * * 1-5`      |
| Meaning  | 6:30 AM UTC, Mon–Fri |
| Catchup  | Disabled            |
| Retries  | 3 (5 min delay)     |

## Configuration

| Variable           | Description                        | Default                     |
|--------------------|------------------------------------|-----------------------------|
| `TRADE_DATA_DIR`   | Base directory for input files     | `modernized/test_data/`     |
| `TRADE_OUTPUT_DIR` | Directory for output files         | `<base_dir>/output/`        |

## Pros

- **Industry standard** — Most widely adopted workflow orchestrator; massive
  community, extensive documentation, and a rich plugin ecosystem.
- **Built-in scheduler & UI** — Web-based monitoring, task logs, Gantt charts,
  and execution history out of the box.
- **Retry & alerting** — Configurable retries, SLAs, and failure callbacks for
  production-grade reliability.
- **Sensor support** — Can wait for external events (files, APIs, databases)
  before starting tasks.
- **Extensibility** — Custom operators, hooks, and connections for any
  integration need.

## Cons

- **Heavy infrastructure** — Requires a scheduler process, metadata database
  (PostgreSQL/MySQL), and web server; overkill for simple pipelines.
- **Learning curve** — DAG authoring, XCom, connections, and the execution
  model take time to learn.
- **XCom limitations** — Not designed for large data transfer between tasks;
  file paths or external storage must be used instead of passing DataFrames
  directly.
- **Cold-start latency** — Task scheduling overhead adds seconds of latency
  per task compared to direct function calls.
- **Python-only** — DAGs must be authored in Python; polyglot pipelines require
  workarounds via BashOperator or external processes.
