"""Task callables for the ``trade_processing`` Airflow DAG.

Each function here is a stage of the shared trade-processing pipeline described
in the modernization spec::

    load CSV -> validate -> enrich (amounts + T+2) -> load confirms ->
    reconcile -> write CSV

All business logic is delegated to the shared :mod:`modernized.common` layer so
that Options A (pandas), B (Dagster) and C (Airflow) produce *identical* output
for the same input.

Inter-task data passing
-----------------------
Airflow runs each task in its own worker process, so in-memory DataFrames cannot
simply be returned and reused by the next task. We therefore pass data in two
ways:

* **Staging files (pickle) for the bulk DataFrames.** Each stage writes its
  output DataFrame to a per-run staging directory (keyed by the run's ``ds``)
  using :meth:`pandas.DataFrame.to_pickle`, which preserves dtypes such as
  ``datetime64`` and ``Int64`` exactly. The next stage reads it back. Pickle is
  used rather than CSV/parquet to avoid dtype loss and an extra ``pyarrow``
  dependency.
* **XCom for the small summary stats.** Every task *returns* a small ``dict`` of
  scalar counts (e.g. ``total_loaded``); Airflow pushes these to XCom, which is
  the recommended channel for small metadata.

The four spec-named callables (:func:`load_and_validate_trades`,
:func:`enrich_trades`, :func:`load_and_reconcile`, :func:`write_results`) are
higher-level groupings that simply compose the per-stage callables. They are
convenient for direct testing of the pipeline without a running scheduler.
"""

from __future__ import annotations

import logging
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modernized.common import config as config_mod
from modernized.common import models, parsers, settlement, validation

logger = logging.getLogger(__name__)

# Repository root: .../investment-etl-pipeline (this file is at
# modernized/option_c_airflow/tasks/trade_tasks.py -> three parents up).
REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "batch_config.ini"

# Directories searched (in order) when resolving input files, after the path
# declared in the config. The legacy Windows drive paths in the .ini never
# resolve on this platform, so these provide the fallback to committed data.
_INPUT_SEARCH_DIRS = [
    REPO_ROOT / "legacy_data" / "trades",
    REPO_ROOT / "modernized" / "test_data",
]

# Output CSV column order required by the spec (uppercase headers).
OUTPUT_COLUMNS = [
    "TRADE_ID",
    "ACCT_NUM",
    "TICKER",
    "SIDE",
    "QTY",
    "PRICE",
    "GROSS_AMT",
    "NET_AMT",
    "COMMISSION",
    "TRADE_DATE",
    "SETTLE_DATE",
    "BROKER",
    "STATUS",
    "RECON_STATUS",
]

_DATE_FMT = "%m/%d/%Y"

# Matches a Windows path (drive letter or any backslash). The legacy config
# stores Windows network-drive paths that are meaningless on this POSIX host, so
# we ignore them rather than letting them create bogus literal directories.
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]|\\")


def _is_local_usable(path_str: str) -> bool:
    """Return True if ``path_str`` is a path we can actually use on this host."""
    return bool(path_str) and not _WINDOWS_PATH_RE.search(path_str)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _normalize_ds(execution_date: Any) -> str:
    """Return the run date as a ``YYYY-MM-DD`` string.

    Accepts a ``datetime``/``date``, a ``YYYY-MM-DD`` string, or anything with a
    ``strftime`` method (e.g. a pendulum ``DateTime`` supplied by Airflow).
    """
    if execution_date is None:
        raise ValueError("execution_date is required")
    if isinstance(execution_date, str):
        # Tolerate full ISO timestamps as well as bare dates.
        return execution_date[:10]
    if isinstance(execution_date, (datetime, date)):
        return execution_date.strftime("%Y-%m-%d")
    if hasattr(execution_date, "strftime"):
        return execution_date.strftime("%Y-%m-%d")
    raise TypeError(f"Unsupported execution_date type: {type(execution_date)!r}")


def _ds_compact(ds: str) -> str:
    """Convert ``YYYY-MM-DD`` to the ``YYYYMMDD`` form used in file names."""
    return ds.replace("-", "")


def _resolve_execution_date(execution_date: Any, kwargs: dict[str, Any]) -> str:
    """Resolve the run date from an explicit arg or the Airflow context."""
    if execution_date is not None:
        return _normalize_ds(execution_date)
    if kwargs.get("ds"):
        return _normalize_ds(kwargs["ds"])
    if kwargs.get("execution_date") is not None:
        return _normalize_ds(kwargs["execution_date"])
    raise ValueError(
        "Could not resolve execution_date from arguments or Airflow context"
    )


def _load_config(config_path: Path | str | None) -> dict[str, Any]:
    """Load the batch config, defaulting to the repo's ``batch_config.ini``."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    return config_mod.load_config(path)


def _find_file(filename: str, configured_dir: str) -> Path:
    """Locate ``filename`` in the configured dir, then the fallback dirs.

    Args:
        filename: Base name to look for (e.g. ``daily_trades_20240115.csv``).
        configured_dir: Directory from the config (often a Windows path that
            does not exist on this platform).

    Returns:
        The first existing path found.

    Raises:
        FileNotFoundError: If the file is not found in any search location.
    """
    candidates: list[Path] = []
    if _is_local_usable(configured_dir):
        candidates.append(Path(configured_dir) / filename)
    candidates.extend(d / filename for d in _INPUT_SEARCH_DIRS)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            # Malformed Windows path on a POSIX host -> just skip it.
            continue

    raise FileNotFoundError(
        f"Could not resolve {filename!r}; searched: "
        + ", ".join(str(c) for c in candidates)
    )


def resolve_trade_file(ds: str, cfg: dict[str, Any]) -> Path:
    """Resolve the daily trade CSV for a run date, with test-data fallback."""
    filename = f"daily_trades_{_ds_compact(ds)}.csv"
    return _find_file(filename, cfg.get("trade_input", ""))


def resolve_confirm_file(ds: str, cfg: dict[str, Any]) -> Path:
    """Resolve the counterparty confirmation file for a run.

    Confirmations are looked up alongside the resolved trade file first (so the
    confirms come from the same dataset as the trades), then in the configured
    directory, then the standard fallback dirs.
    """
    filename = "counterparty_confirms.dat"
    trade_dir = resolve_trade_file(ds, cfg).parent
    candidate = trade_dir / filename
    if candidate.is_file():
        return candidate
    return _find_file(filename, cfg.get("trade_input", ""))


def _staging_dir(ds: str) -> Path:
    """Per-run staging directory for intermediate DataFrames."""
    staging = Path(tempfile.gettempdir()) / "trade_processing" / ds
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def _stage_path(ds: str, name: str) -> Path:
    """Path to a named staging artifact for a run."""
    return _staging_dir(ds) / f"{name}.pkl"


def _output_dir(cfg: dict[str, Any]) -> Path:
    """Resolve a writable output directory, falling back to a local folder."""
    configured = cfg.get("report_output", "")
    if _is_local_usable(configured):
        candidate = Path(configured)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            # Not writable -> fall through to local output.
            pass
    fallback = REPO_ROOT / "modernized" / "option_c_airflow" / "output"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


# --------------------------------------------------------------------------- #
# Per-stage task callables (one per DAG PythonOperator)
# --------------------------------------------------------------------------- #
def load_trades(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 1 — load the daily trade CSV via the common parser.

    Returns a stats dict with ``total_loaded`` and the resolved trade-file path.
    """
    ds = _resolve_execution_date(execution_date, kwargs)
    cfg = _load_config(config_path)
    trade_file = resolve_trade_file(ds, cfg)

    logger.info("Loading trades for %s from %s", ds, trade_file)
    df = parsers.load_trades_csv(trade_file)
    df.to_pickle(_stage_path(ds, "raw_trades"))

    total_loaded = int(len(df))
    logger.info("Loaded %d raw trade rows", total_loaded)
    return {"ds": ds, "total_loaded": total_loaded, "trade_file": str(trade_file)}


def validate_trades(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 2 — validate trades and split into valid/error frames.

    ``duplicates_removed`` counts error rows whose ``error_reason`` is
    ``DUPLICATE``; ``validation_errors`` counts the remaining (non-duplicate)
    error rows.
    """
    ds = _resolve_execution_date(execution_date, kwargs)
    raw = pd.read_pickle(_stage_path(ds, "raw_trades"))

    valid, errors = validation.validate_trades(raw)

    if errors.empty:
        duplicates_removed = 0
        validation_errors = 0
    else:
        is_dup = errors["error_reason"] == "DUPLICATE"
        duplicates_removed = int(is_dup.sum())
        validation_errors = int((~is_dup).sum())

    valid.to_pickle(_stage_path(ds, "valid_trades"))
    errors.to_pickle(_stage_path(ds, "error_trades"))

    logger.info(
        "Validation: %d valid, %d duplicates removed, %d validation errors",
        len(valid),
        duplicates_removed,
        validation_errors,
    )
    return {
        "ds": ds,
        "valid_count": int(len(valid)),
        "duplicates_removed": duplicates_removed,
        "validation_errors": validation_errors,
    }


def enrich_trades(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 3 — compute gross/net amounts and fill missing T+2 settle dates."""
    ds = _resolve_execution_date(execution_date, kwargs)
    valid = pd.read_pickle(_stage_path(ds, "valid_trades")).copy()

    valid["gross_amount"] = (valid["quantity"] * valid["price"]).round(2)

    def _net(row: pd.Series) -> float:
        gross = row["gross_amount"]
        commission = row["commission"]
        if row["side"] == "BUY":
            return round(gross + commission, 2)
        return round(gross - commission, 2)

    valid["net_amount"] = valid.apply(_net, axis=1)

    # Fill missing settlement dates (NaT) using the common T+2 calculator.
    missing_settle = valid["settle_date"].isna()
    for idx in valid.index[missing_settle]:
        trade_dt = valid.at[idx, "trade_date"].date()
        valid.at[idx, "settle_date"] = pd.Timestamp(
            settlement.calculate_t_plus_2(trade_dt)
        )

    valid.to_pickle(_stage_path(ds, "enriched_trades"))
    logger.info(
        "Enriched %d trades (%d settle dates filled via T+2)",
        len(valid),
        int(missing_settle.sum()),
    )
    return {
        "ds": ds,
        "enriched_count": int(len(valid)),
        "settle_dates_filled": int(missing_settle.sum()),
    }


def load_confirms(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 4 — load broker confirmations via the common parser."""
    ds = _resolve_execution_date(execution_date, kwargs)
    cfg = _load_config(config_path)
    confirm_file = resolve_confirm_file(ds, cfg)

    logger.info("Loading confirms for %s from %s", ds, confirm_file)
    confirms = parsers.load_counterparty_file(confirm_file)
    confirms.to_pickle(_stage_path(ds, "confirms"))

    logger.info("Loaded %d confirmation rows", len(confirms))
    return {
        "ds": ds,
        "confirms_loaded": int(len(confirms)),
        "confirm_file": str(confirm_file),
    }


def reconcile(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 5 — reconcile enriched trades against confirms (REQUIRED logic).

    Performs a LEFT merge on ``trade_id`` and classifies each row as
    ``UNMATCHED`` / ``PRICE_BREAK`` / ``QTY_BREAK`` / ``MATCHED``.
    """
    ds = _resolve_execution_date(execution_date, kwargs)
    enriched = pd.read_pickle(_stage_path(ds, "enriched_trades"))
    confirms = pd.read_pickle(_stage_path(ds, "confirms"))

    merged = enriched.merge(
        confirms, on="trade_id", how="left", suffixes=("", "_confirm")
    )

    def _status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(row["price"] - row["price_confirm"]) > 0.01:
            return "PRICE_BREAK"
        if row["quantity"] != row["quantity_confirm"]:
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_status, axis=1)

    matched = int((merged["recon_status"] == "MATCHED").sum())
    breaks = int(
        merged["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
    )
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())

    merged.to_pickle(_stage_path(ds, "reconciled"))
    logger.info(
        "Reconciliation: %d matched, %d breaks, %d unmatched",
        matched,
        breaks,
        unmatched,
    )
    return {
        "ds": ds,
        "matched": matched,
        "breaks": breaks,
        "unmatched": unmatched,
    }


def write_output(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Stage 6 — write the trade report CSV and the error log.

    Returns the full :class:`ProcessingResult` summary as a dict plus the output
    paths. This pulls the per-stage stats back from XCom when available so the
    summary is complete; when called directly (no Airflow), it recomputes the
    duplicate/validation/recon counts from the staged frames.
    """
    ds = _resolve_execution_date(execution_date, kwargs)
    cfg = _load_config(config_path)

    reconciled = pd.read_pickle(_stage_path(ds, "reconciled"))
    errors = pd.read_pickle(_stage_path(ds, "error_trades"))
    raw = pd.read_pickle(_stage_path(ds, "raw_trades"))

    out_dir = _output_dir(cfg)
    compact = _ds_compact(ds)
    report_path = out_dir / f"trade_report_{compact}.csv"
    error_path = out_dir / f"trade_errors_{compact}.csv"

    report = pd.DataFrame(
        {
            "TRADE_ID": reconciled["trade_id"],
            "ACCT_NUM": reconciled["account"],
            "TICKER": reconciled["ticker"],
            "SIDE": reconciled["side"],
            "QTY": reconciled["quantity"],
            "PRICE": reconciled["price"],
            "GROSS_AMT": reconciled["gross_amount"],
            "NET_AMT": reconciled["net_amount"],
            "COMMISSION": reconciled["commission"],
            "TRADE_DATE": reconciled["trade_date"].dt.strftime(_DATE_FMT),
            "SETTLE_DATE": reconciled["settle_date"].dt.strftime(_DATE_FMT),
            "BROKER": reconciled["broker"],
            "STATUS": reconciled["status"],
            "RECON_STATUS": reconciled["recon_status"],
        }
    )[OUTPUT_COLUMNS]

    with report_path.open("w", newline="", encoding="utf-8") as fh:
        report.to_csv(fh, index=False)
    logger.info("Wrote trade report (%d rows) to %s", len(report), report_path)

    # Error log: the error rows and their reason. Keep it readable even if empty.
    if errors.empty:
        error_log = pd.DataFrame(columns=["trade_id", "error_reason"])
    else:
        keep = [c for c in ["trade_id", "error_reason"] if c in errors.columns]
        error_log = errors[keep]
    with error_path.open("w", newline="", encoding="utf-8") as fh:
        error_log.to_csv(fh, index=False)
    logger.info("Wrote error log (%d rows) to %s", len(error_log), error_path)

    # Recompute the full summary from the staged frames so write_output can stand
    # alone (e.g. in direct testing) without depending on upstream XCom values.
    if errors.empty:
        duplicates_removed = 0
        validation_errors = 0
    else:
        is_dup = errors["error_reason"] == "DUPLICATE"
        duplicates_removed = int(is_dup.sum())
        validation_errors = int((~is_dup).sum())

    result = models.ProcessingResult(
        total_loaded=int(len(raw)),
        duplicates_removed=duplicates_removed,
        validation_errors=validation_errors,
        matched=int((reconciled["recon_status"] == "MATCHED").sum()),
        breaks=int(
            reconciled["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
        ),
        unmatched=int((reconciled["recon_status"] == "UNMATCHED").sum()),
    )

    summary = result.model_dump()
    summary.update(
        {
            "ds": ds,
            "report_path": str(report_path),
            "error_path": str(error_path),
        }
    )
    logger.info("Processing summary for %s: %s", ds, result.model_dump())
    return summary


# --------------------------------------------------------------------------- #
# Spec-named composite callables (load -> validate, enrich, load -> reconcile,
# write). These compose the per-stage callables above and are convenient for
# direct testing without a running Airflow scheduler.
# --------------------------------------------------------------------------- #
def load_and_validate_trades(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Load and validate trades; return combined stats."""
    ds = _resolve_execution_date(execution_date, kwargs)
    load_stats = load_trades(execution_date=ds, config_path=config_path)
    validate_stats = validate_trades(execution_date=ds, config_path=config_path)
    return {**load_stats, **validate_stats}


def load_and_reconcile(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Load confirms and reconcile against enriched trades (REQUIRED logic)."""
    ds = _resolve_execution_date(execution_date, kwargs)
    confirm_stats = load_confirms(execution_date=ds, config_path=config_path)
    recon_stats = reconcile(execution_date=ds, config_path=config_path)
    return {**confirm_stats, **recon_stats}


def write_results(
    execution_date: Any = None, config_path: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Write the output report and error log; return the full summary."""
    ds = _resolve_execution_date(execution_date, kwargs)
    return write_output(execution_date=ds, config_path=config_path)


def run_pipeline(execution_date: Any = None, config_path: Any = None) -> models.ProcessingResult:
    """Run the full pipeline end-to-end in-process and return the summary.

    This is the convenience entry point used by the test harness; the Airflow DAG
    instead wires the per-stage callables together as separate tasks.
    """
    ds = _resolve_execution_date(execution_date, {})
    load_and_validate_trades(execution_date=ds, config_path=config_path)
    enrich_trades(execution_date=ds, config_path=config_path)
    load_and_reconcile(execution_date=ds, config_path=config_path)
    summary = write_results(execution_date=ds, config_path=config_path)
    return models.ProcessingResult(
        total_loaded=summary["total_loaded"],
        duplicates_removed=summary["duplicates_removed"],
        validation_errors=summary["validation_errors"],
        matched=summary["matched"],
        breaks=summary["breaks"],
        unmatched=summary["unmatched"],
    )
