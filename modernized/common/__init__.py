"""Shared modernization layer for Meridian Capital trade processing.

This package contains the reusable building blocks (models, parsers, validation,
settlement, and config) used by all three modernization prototypes:

* ``option_a_pandas``  - standalone Pandas + Pydantic script
* ``option_b_dagster`` - Dagster asset graph
* ``option_c_airflow`` - Airflow DAG

The intent is that the bulk of the business logic lives here so the three
options differ only in their orchestration/execution model.
"""

from modernized.common import config, models, parsers, settlement, validation

__all__ = ["config", "models", "parsers", "settlement", "validation"]
