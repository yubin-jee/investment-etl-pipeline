"""Airflow DAG for daily trade processing.

Orchestrates trade ingestion, validation, enrichment, reconciliation,
and output using the shared common layer.

Schedule: 6:30 AM weekdays (Mon-Fri)

Task graph:
    wait_for_trade_file >> load_trades >> validate >> enrich
                                                        ▼
                                              load_confirms >> reconcile >> write_output
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.filesystem import FileSensor

from modernized.option_c_airflow.tasks.trade_tasks import (
    enrich_trades,
    load_and_reconcile,
    load_and_validate_trades,
    write_results,
)

default_args = {
    "owner": "meridian-data-engineering",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "email": ["data-eng@meridian-capital.com"],
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=1),
}


def _on_failure_callback(context: dict) -> None:
    """Alert callback for task failures.

    Logs the failure details. In production, this would send a Slack
    notification, PagerDuty alert, or email.
    """
    task_instance = context.get("task_instance")
    exception = context.get("exception")
    dag_id = context.get("dag", {})
    print(
        f"ALERT: Task {task_instance} in DAG {dag_id} failed with: {exception}"
    )


with DAG(
    dag_id="trade_processing",
    default_args=default_args,
    description="Daily trade processing: ingest, validate, enrich, reconcile",
    schedule_interval="30 6 * * 1-5",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["trades", "meridian", "daily"],
    max_active_runs=1,
) as dag:

    wait_for_trade_file = FileSensor(
        task_id="wait_for_trade_file",
        filepath="legacy_data/trades/daily_trades_{{ ds_nodash }}.csv",
        poke_interval=60,
        timeout=3600,
        mode="poke",
        on_failure_callback=_on_failure_callback,
    )

    load_and_validate = PythonOperator(
        task_id="load_and_validate_trades",
        python_callable=load_and_validate_trades,
        on_failure_callback=_on_failure_callback,
    )

    enrich = PythonOperator(
        task_id="enrich_trades",
        python_callable=enrich_trades,
        on_failure_callback=_on_failure_callback,
    )

    reconcile = PythonOperator(
        task_id="load_and_reconcile",
        python_callable=load_and_reconcile,
        on_failure_callback=_on_failure_callback,
    )

    write_output = PythonOperator(
        task_id="write_results",
        python_callable=write_results,
        on_failure_callback=_on_failure_callback,
    )

    # Define task dependencies
    wait_for_trade_file >> load_and_validate >> enrich >> reconcile >> write_output
