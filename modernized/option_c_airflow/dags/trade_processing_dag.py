"""Airflow DAG for daily trade processing pipeline.

Orchestrates the four-stage trade processing workflow:
  1. Load & validate trades from CSV
  2. Enrich with calculated amounts and settlement dates
  3. Reconcile against counterparty confirmations
  4. Write final output and error logs

Schedule: 6:30 AM UTC, weekdays only (Mon–Fri).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:
    from airflow.operators.python import PythonOperator

from modernized.option_c_airflow.tasks.trade_tasks import (
    enrich_trades,
    load_and_reconcile,
    load_and_validate_trades,
    write_results,
)

logger = logging.getLogger(__name__)


def on_failure_callback(context):
    """Log task failure details for alerting and diagnostics."""
    task_instance = context.get("task_instance")
    exception = context.get("exception")
    logger.error(
        "Task %s in DAG %s failed on %s: %s",
        task_instance.task_id if task_instance else "unknown",
        task_instance.dag_id if task_instance else "unknown",
        context.get("execution_date"),
        exception,
    )


default_args = {
    "owner": "meridian_ops",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": on_failure_callback,
}

with DAG(
    dag_id="trade_processing",
    default_args=default_args,
    description="Daily trade processing: load, validate, enrich, reconcile, output",
    schedule="30 6 * * 1-5",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["trades", "meridian", "etl"],
) as dag:
    load_validate = PythonOperator(
        task_id="load_validate",
        python_callable=load_and_validate_trades,
    )

    enrich = PythonOperator(
        task_id="enrich",
        python_callable=enrich_trades,
    )

    load_reconcile = PythonOperator(
        task_id="load_reconcile",
        python_callable=load_and_reconcile,
    )

    write_output = PythonOperator(
        task_id="write_output",
        python_callable=write_results,
    )

    load_validate >> enrich >> load_reconcile >> write_output
