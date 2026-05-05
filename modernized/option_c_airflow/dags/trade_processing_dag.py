"""Airflow DAG definition for the Meridian Capital trade processing pipeline.

Orchestrates the daily trade ingestion, validation, enrichment,
counterparty reconciliation, and output generation workflow.
"""

import logging
from datetime import datetime, timedelta

from airflow import DAG
try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:
    from airflow.operators.python import PythonOperator

from modernized.option_c_airflow.tasks.trade_tasks import (
    enrich_trades,
    load_confirms,
    load_trades,
    reconcile,
    validate_trades_task,
    write_output,
)

logger = logging.getLogger(__name__)


def _on_failure_callback(context: dict) -> None:
    """Log task failure details for alerting and debugging."""
    ti = context.get("task_instance")
    dag_id = context.get("dag", ti.dag_id if ti else "unknown")
    task_id = ti.task_id if ti else "unknown"
    execution_date = context.get("execution_date", "unknown")
    exception = context.get("exception", "N/A")

    logger.error(
        "Task FAILED — dag=%s  task=%s  execution_date=%s  exception=%s",
        dag_id,
        task_id,
        execution_date,
        exception,
    )


default_args = {
    "owner": "meridian_data_team",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": _on_failure_callback,
}

doc_md = """
### Trade Processing Pipeline

**Owner:** Meridian Capital Partners — Data Engineering

This DAG orchestrates the daily batch trade processing workflow:

1. **load_trades** — Ingest the daily trade CSV file.
2. **validate_trades** — Validate trades against Pydantic models and broker whitelist.
3. **enrich_trades** — Calculate gross/net amounts and fill missing settlement dates (T+2).
4. **load_confirms** — Ingest counterparty confirmation file (runs in parallel with steps 1-3).
5. **reconcile** — Left-join enriched trades with confirmations; classify as MATCHED / PRICE_BREAK / QTY_BREAK / UNMATCHED.
6. **write_output** — Write the final reconciled CSV.

**Schedule:** 6:30 AM UTC, weekdays only (Mon–Fri).

**Retry policy:** Each task retries up to 3 times with a 5-minute delay.
"""

with DAG(
    dag_id="trade_processing",
    default_args=default_args,
    description="Daily trade processing: ingest, validate, enrich, reconcile, output",
    schedule="30 6 * * 1-5",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    doc_md=doc_md,
    tags=["trades", "meridian", "etl"],
) as dag:

    load_trades_op = PythonOperator(
        task_id="load_trades",
        python_callable=load_trades,
    )

    validate_op = PythonOperator(
        task_id="validate_trades",
        python_callable=validate_trades_task,
    )

    enrich_op = PythonOperator(
        task_id="enrich_trades",
        python_callable=enrich_trades,
    )

    load_confirms_op = PythonOperator(
        task_id="load_confirms",
        python_callable=load_confirms,
    )

    reconcile_op = PythonOperator(
        task_id="reconcile",
        python_callable=reconcile,
    )

    write_output_op = PythonOperator(
        task_id="write_output",
        python_callable=write_output,
    )

    # Task dependencies:
    # load_trades >> validate >> enrich ──┐
    #                                     ├──> reconcile >> write_output
    # load_confirms ──────────────────────┘
    load_trades_op >> validate_op >> enrich_op
    [enrich_op, load_confirms_op] >> reconcile_op >> write_output_op
