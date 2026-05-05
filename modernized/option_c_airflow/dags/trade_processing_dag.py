"""Airflow DAG for daily trade processing.

Orchestrates the Meridian Capital Partners trade pipeline:
load → validate → enrich → reconcile → write, with counterparty
confirms loaded in parallel.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:
    from airflow.operators.python import PythonOperator

from modernized.option_c_airflow.tasks.trade_tasks import (
    enrich_trades_task,
    load_confirms_task,
    load_trades_task,
    reconcile_task,
    validate_trades_task,
    write_output_task,
    _on_failure_callback,
)

default_args = {
    "owner": "meridian-ops",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": _on_failure_callback,
}

with DAG(
    dag_id="trade_processing",
    default_args=default_args,
    schedule="30 6 * * 1-5",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    doc_md="""
### Trade Processing Pipeline

Daily batch pipeline for Meridian Capital Partners that processes
trade files, validates against Pydantic models, enriches with
calculated amounts and settlement dates, reconciles with
counterparty confirmations, and writes the final report.

**Schedule:** 6:30 AM UTC, Monday–Friday.
""",
) as dag:

    load_trades = PythonOperator(
        task_id="load_trades",
        python_callable=load_trades_task,
    )

    validate_trades = PythonOperator(
        task_id="validate_trades",
        python_callable=validate_trades_task,
    )

    enrich_trades = PythonOperator(
        task_id="enrich_trades",
        python_callable=enrich_trades_task,
    )

    load_confirms = PythonOperator(
        task_id="load_confirms",
        python_callable=load_confirms_task,
    )

    reconcile = PythonOperator(
        task_id="reconcile",
        python_callable=reconcile_task,
    )

    write_output = PythonOperator(
        task_id="write_output",
        python_callable=write_output_task,
    )

    # Define task dependencies:
    # load_trades → validate → enrich ──┐
    #                                    ├─→ reconcile → write_output
    # load_confirms ────────────────────┘
    load_trades >> validate_trades >> enrich_trades
    [enrich_trades, load_confirms] >> reconcile >> write_output
