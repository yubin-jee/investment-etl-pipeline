"""Airflow DAG for the daily trade-processing pipeline (Option C).

The DAG mirrors the legacy ``legacy_scripts/process_trades.py`` batch but as a
graph of independent, retryable Airflow tasks. Each task delegates to a callable
in :mod:`modernized.option_c_airflow.tasks.trade_tasks`, which in turn calls the
shared :mod:`modernized.common` layer — so the output is identical to Options A
and B.

Schedule
--------
``schedule_interval="30 6 * * 1-5"`` — 6:30 AM on weekdays (Mon–Fri), matching
the legacy Windows Task Scheduler entry ``trade_processing = 06:30``.

Data flow between tasks
-----------------------
Bulk DataFrames are handed off via per-run staging pickle files (keyed by the
run's ``ds``); the small per-stage summary dicts travel through XCom. See the
module docstring of ``trade_tasks`` for the rationale.

File gating
-----------
A :class:`~airflow.sensors.filesystem.FileSensor` waits for the day's trade CSV
to land before any processing starts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.filesystem import FileSensor

from modernized.option_c_airflow.tasks import trade_tasks

logger = logging.getLogger(__name__)


def alert_on_failure(context: dict) -> None:
    """``on_failure_callback`` stub — log an alert for a failed task instance.

    In production this would page an on-call engineer (PagerDuty/Opsgenie) or
    send to the SMTP recipients configured in ``batch_config.ini``. Here we just
    log so the DAG stays dependency-free and import-clean.
    """
    task_instance = context.get("task_instance")
    exception = context.get("exception")
    logger.error(
        "ALERT: trade_processing task failed | task=%s | run=%s | error=%s",
        getattr(task_instance, "task_id", "unknown"),
        context.get("ds", "unknown"),
        exception,
    )


# Resolve the trade-input directory for the FileSensor. We point the sensor at
# the committed test-data file so the DAG is runnable out of the box; in
# production this would be the configured ``trade_input`` share.
_TRADE_INPUT_FILEPATH = str(
    trade_tasks.REPO_ROOT
    / "modernized"
    / "test_data"
    / "daily_trades_20240115.csv"
)

default_args = {
    "owner": "meridian-ops",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": alert_on_failure,
}

with DAG(
    dag_id="trade_processing",
    description="Daily trade ingestion, validation, enrichment and reconciliation.",
    schedule_interval="30 6 * * 1-5",  # 6:30 AM, weekdays
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["meridian", "trades", "option-c"],
) as dag:

    wait_for_trade_file = FileSensor(
        task_id="wait_for_trade_file",
        filepath=_TRADE_INPUT_FILEPATH,
        poke_interval=60,
        timeout=60 * 60,  # give up after an hour
        mode="reschedule",  # free the worker slot between pokes
    )

    load_trades = PythonOperator(
        task_id="load_trades",
        python_callable=trade_tasks.load_trades,
    )

    validate_trades = PythonOperator(
        task_id="validate_trades",
        python_callable=trade_tasks.validate_trades,
    )

    enrich_trades = PythonOperator(
        task_id="enrich_trades",
        python_callable=trade_tasks.enrich_trades,
    )

    load_confirms = PythonOperator(
        task_id="load_confirms",
        python_callable=trade_tasks.load_confirms,
    )

    reconcile = PythonOperator(
        task_id="reconcile",
        python_callable=trade_tasks.reconcile,
    )

    write_output = PythonOperator(
        task_id="write_output",
        python_callable=trade_tasks.write_output,
    )

    # Dependency graph: gate on the file, then run the linear pipeline. Confirms
    # only need to be loaded before reconciliation, so load_confirms runs in
    # parallel with the trade enrichment branch and both feed reconcile.
    wait_for_trade_file >> load_trades >> validate_trades >> enrich_trades
    enrich_trades >> reconcile
    load_trades >> load_confirms >> reconcile
    reconcile >> write_output
