"""DuckDB-based trade ingestion and validation."""

from __future__ import annotations

import duckdb
import pandas as pd

from ingest import VALID_BROKERS

# Column type casts applied inside the ``read_csv_auto`` wrapper.
_COL_CASTS = """
    CAST(TRADE_ID AS VARCHAR)   AS trade_id,
    CAST(ACCT_NUM AS VARCHAR)   AS account,
    CAST(TICKER AS VARCHAR)     AS ticker,
    CAST(SIDE AS VARCHAR)       AS side,
    CAST(QTY AS DOUBLE)         AS quantity,
    CAST(PRICE AS DOUBLE)       AS price,
    CAST(TRADE_DATE AS VARCHAR) AS trade_date,
    CAST(SETTLE_DATE AS VARCHAR) AS settle_date,
    CAST(BROKER AS VARCHAR)     AS broker,
    CAST(COMMISSION AS DOUBLE)  AS commission,
    CAST(STATUS AS VARCHAR)     AS status
"""


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Return a fresh in-process DuckDB connection."""
    return duckdb.connect(":memory:")


def load_trades(file_path: str) -> pd.DataFrame:
    """Load trades from a CSV file via DuckDB, returning a pandas DataFrame.

    Parameters
    ----------
    file_path:
        Path to the daily trades CSV.

    Returns
    -------
    pandas.DataFrame
    """
    con = _get_connection()
    query = f"""
        SELECT {_COL_CASTS}
        FROM read_csv_auto('{file_path}', header=true, all_varchar=false)
    """
    df = con.sql(query).df()

    # Parse dates into pandas Timestamps for consistency with other modules.
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%m/%d/%Y", errors="coerce")
    df["settle_date"] = pd.to_datetime(df["settle_date"], format="%m/%d/%Y", errors="coerce")
    con.close()
    return df


def validate_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate trades using SQL and return accepted and rejected rows.

    Parameters
    ----------
    df:
        Raw trade data as returned by :func:`load_trades`.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        ``(clean_df, rejected_df)`` where *rejected_df* includes a
        ``rejection_reason`` column.
    """
    con = _get_connection()

    # Add a synthetic row index so we can preserve insertion order for
    # duplicate detection (``rowid`` is unavailable on registered DataFrames).
    df_indexed = df.copy()
    df_indexed["_row_idx"] = range(len(df_indexed))
    con.register("raw_trades", df_indexed)

    # Build the valid-brokers list for SQL IN clause.
    brokers_sql = ", ".join(f"'{b}'" for b in VALID_BROKERS)

    # Classify every row with a rejection reason (NULL means valid).
    classify_sql = f"""
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY trade_id ORDER BY _row_idx) AS _rn
            FROM raw_trades
        ),
        classified AS (
            SELECT *,
                CASE
                    WHEN _rn > 1 THEN 'duplicate_trade_id'
                    WHEN broker NOT IN ({brokers_sql}) THEN 'invalid_broker'
                    WHEN quantity <= 0 THEN 'non_positive_quantity'
                    WHEN price <= 0 THEN 'non_positive_price'
                    WHEN price IS NULL THEN 'missing_price'
                    ELSE NULL
                END AS rejection_reason
            FROM ranked
        )
        SELECT * FROM classified
    """

    full = con.sql(classify_sql).df()
    full.drop(columns=["_rn", "_row_idx"], inplace=True)

    clean_df = full.loc[full["rejection_reason"].isna()].drop(columns=["rejection_reason"]).reset_index(drop=True)
    rejected_df = full.loc[full["rejection_reason"].notna()].reset_index(drop=True)

    con.close()
    return clean_df, rejected_df
