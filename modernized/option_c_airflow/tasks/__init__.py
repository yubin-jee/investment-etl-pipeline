"""Airflow task callables for the trade-processing DAG.

The callables in :mod:`modernized.option_c_airflow.tasks.trade_tasks` are thin
orchestration wrappers around the shared :mod:`modernized.common` layer. They are
written so they can be invoked both by Airflow ``PythonOperator`` tasks (which
inject the task context as ``**kwargs``) and directly from a test harness with
explicit ``execution_date``/``config_path`` arguments.
"""
