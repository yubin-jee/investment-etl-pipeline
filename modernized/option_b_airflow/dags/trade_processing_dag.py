"""Option B: Airflow DAG for trade processing.

Defines an Airflow DAG with discrete tasks matching the 6-step pipeline.
Each task is a PythonOperator wrapping functions from trade_tasks.py.

DAG schedule: weekdays at 6:30 AM (``30 6 * * 1-5``).

Note: Full Airflow deployment is out of scope — import this file into an
Airflow environment, or test the task functions standalone via trade_tasks.py.
"""

from __future__ import annotations

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    AIRFLOW_AVAILABLE = True
except ImportError:
    AIRFLOW_AVAILABLE = False

from datetime import datetime, timedelta

# The task functions are importable regardless of Airflow
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from modernized.option_b_airflow.tasks.trade_tasks import (
    calculate_amounts_task,
    load_trades,
    parse_confirms_task,
    reconcile_task,
    validate_trades_task,
    write_output_csv_task,
    write_to_db_task,
)

DAG_ID = "trade_processing_pipeline"
DEFAULT_ARGS = {
    "owner": "meridian_capital",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2024, 3, 1),
}


def _get_trade_date(**context):
    """Derive trade date from the Airflow execution date."""
    execution_date = context.get("ds_nodash")
    return execution_date or datetime.now().strftime("%Y%m%d")


if AIRFLOW_AVAILABLE:
    with DAG(
        dag_id=DAG_ID,
        default_args=DEFAULT_ARGS,
        description="Daily trade processing pipeline — modernized ETL",
        schedule_interval="30 6 * * 1-5",  # weekdays at 6:30 AM
        catchup=False,
        max_active_runs=1,
        tags=["trades", "etl", "meridian"],
    ) as dag:

        def _load(**ctx):
            trade_date = _get_trade_date(**ctx)
            result = load_trades(trade_date)
            ctx["ti"].xcom_push(key="raw_trades", value=result)

        def _validate(**ctx):
            raw = ctx["ti"].xcom_pull(key="raw_trades", task_ids="load_trades")
            valid, errors = validate_trades_task(raw)
            ctx["ti"].xcom_push(key="valid_trades", value=valid)
            ctx["ti"].xcom_push(key="validation_errors", value=errors)

        def _calculate(**ctx):
            valid = ctx["ti"].xcom_pull(key="valid_trades", task_ids="validate_trades")
            result = calculate_amounts_task(valid)
            ctx["ti"].xcom_push(key="enriched_trades", value=result)

        def _parse_confirms(**ctx):
            trade_date = _get_trade_date(**ctx)
            result = parse_confirms_task(trade_date)
            ctx["ti"].xcom_push(key="confirms", value=result)

        def _reconcile(**ctx):
            enriched = ctx["ti"].xcom_pull(
                key="enriched_trades", task_ids="calculate_amounts"
            )
            confirms = ctx["ti"].xcom_pull(
                key="confirms", task_ids="parse_confirms"
            )
            result = reconcile_task(enriched, confirms)
            ctx["ti"].xcom_push(key="reconciled_trades", value=result)

        def _write_db(**ctx):
            reconciled = ctx["ti"].xcom_pull(
                key="reconciled_trades", task_ids="reconcile"
            )
            write_to_db_task(reconciled)

        def _write_csv(**ctx):
            reconciled = ctx["ti"].xcom_pull(
                key="reconciled_trades", task_ids="reconcile"
            )
            trade_date = _get_trade_date(**ctx)
            write_output_csv_task(reconciled, trade_date)

        t_load = PythonOperator(
            task_id="load_trades",
            python_callable=_load,
            provide_context=True,
        )
        t_validate = PythonOperator(
            task_id="validate_trades",
            python_callable=_validate,
            provide_context=True,
        )
        t_calculate = PythonOperator(
            task_id="calculate_amounts",
            python_callable=_calculate,
            provide_context=True,
        )
        t_parse_confirms = PythonOperator(
            task_id="parse_confirms",
            python_callable=_parse_confirms,
            provide_context=True,
        )
        t_reconcile = PythonOperator(
            task_id="reconcile",
            python_callable=_reconcile,
            provide_context=True,
        )
        t_write_db = PythonOperator(
            task_id="write_to_db",
            python_callable=_write_db,
            provide_context=True,
        )
        t_write_csv = PythonOperator(
            task_id="write_output_csv",
            python_callable=_write_csv,
            provide_context=True,
        )

        # Task dependency graph:
        #
        #   load_trades
        #       |
        #   validate_trades
        #       |
        #   calculate_amounts ── parse_confirms
        #       \                   /
        #        \                 /
        #          reconcile
        #         /         \
        #   write_to_db   write_output_csv

        t_load >> t_validate >> t_calculate
        t_calculate >> t_reconcile
        t_parse_confirms >> t_reconcile
        t_reconcile >> [t_write_db, t_write_csv]
