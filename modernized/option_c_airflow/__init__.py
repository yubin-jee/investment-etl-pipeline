"""Option C: Apache Airflow orchestration of the trade-processing pipeline.

This package expresses the legacy ``legacy_scripts/process_trades.py`` pipeline
as an Airflow DAG. All business logic lives in the shared
:mod:`modernized.common` layer; this package only adds orchestration (a DAG, a
file sensor, retries, and per-stage ``PythonOperator`` tasks).
"""
