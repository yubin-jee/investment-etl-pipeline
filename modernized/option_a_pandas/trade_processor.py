"""Option A: Pandas + Pydantic standalone trade processor.

A single-script modernization of ``legacy_scripts/process_trades.py``. It drives
the shared :mod:`modernized.common` layer (parsing, validation, settlement,
config, Pydantic models) to run the full daily trade pipeline:

    load config -> load trades -> validate -> enrich -> load confirms
    -> reconcile -> write report + error log -> summarize

Run from the repository root so the ``modernized`` package resolves::

    python -m modernized.option_a_pandas.trade_processor --date 20240115
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from modernized.common import config, parsers, settlement, validation
from modernized.common.models import ProcessingResult

logger = logging.getLogger(__name__)

#: Output CSV header, in the exact order required by all three options.
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

#: Tolerance (USD) used for the price-break reconciliation check.
PRICE_BREAK_TOLERANCE = 0.01

#: Date format used for both parsing fallbacks and report output.
DATE_FORMAT = "%m/%d/%Y"


def _resolve_input_file(
    configured_dir: str, filename: str, run_date: str
) -> Path:
    """Resolve an input file by trying each known location in order.

    Resolution order (first existing path wins):

    1. The directory configured in ``batch_config.ini`` (the original Windows
       network-drive path, e.g. ``C:\\MeridianData\\trades\\``). This will not
       exist off the production Windows hosts.
    2. ``modernized/test_data/<filename>`` (committed sample data).
    3. ``legacy_data/trades/<filename>`` (real legacy flat files).

    Args:
        configured_dir: Directory from the config file (may be a Windows path).
        filename: The file name to look for in each candidate directory.
        run_date: The run date (``YYYYMMDD``); only used for logging context.

    Returns:
        The first candidate path that exists.

    Raises:
        FileNotFoundError: If none of the candidate paths exist.
    """
    candidates: list[Path] = []
    if configured_dir:
        candidates.append(Path(configured_dir) / filename)
    candidates.append(Path("modernized/test_data") / filename)
    candidates.append(Path("legacy_data/trades") / filename)

    for candidate in candidates:
        if candidate.exists():
            logger.info("Resolved input '%s' -> %s", filename, candidate)
            return candidate

    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"Could not locate '{filename}' for run_date {run_date}. Tried: {tried}"
    )


def _resolve_output_dir(configured_dir: str) -> Path:
    """Pick a writable output directory, falling back to a local folder.

    Args:
        configured_dir: The ``report_output`` directory from the config file.

    Returns:
        The configured directory if it exists, otherwise a local
        ``modernized/option_a_pandas/output`` directory (created if needed).
    """
    if configured_dir and Path(configured_dir).is_dir():
        return Path(configured_dir)
    fallback = Path("modernized/option_a_pandas/output")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _enrich_trades(valid: pd.DataFrame) -> pd.DataFrame:
    """Add gross/net amounts and fill missing settlement dates.

    Args:
        valid: The validated trades DataFrame.

    Returns:
        A copy of ``valid`` with ``gross_amount``, ``net_amount`` and
        filled-in ``settle_date`` columns.
    """
    enriched = valid.copy()
    enriched["gross_amount"] = (
        enriched["quantity"] * enriched["price"]
    ).round(2)

    # BUY adds commission to the cost; SELL nets it out of proceeds.
    is_buy = enriched["side"] == "BUY"
    enriched["net_amount"] = (
        enriched["gross_amount"]
        + enriched["commission"].where(is_buy, -enriched["commission"])
    ).round(2)

    missing_settle = enriched["settle_date"].isna()
    if missing_settle.any():
        enriched.loc[missing_settle, "settle_date"] = enriched.loc[
            missing_settle, "trade_date"
        ].apply(lambda ts: pd.Timestamp(settlement.calculate_t_plus_2(ts.date())))

    return enriched


def _classify_recon(row: pd.Series) -> str:
    """Determine the reconciliation status for a single merged trade row.

    Args:
        row: A row from the left-merged trades/confirms DataFrame.

    Returns:
        One of ``"UNMATCHED"``, ``"PRICE_BREAK"``, ``"QTY_BREAK"`` or
        ``"MATCHED"``.
    """
    if pd.isna(row["price_confirm"]):
        return "UNMATCHED"
    if abs(row["price"] - row["price_confirm"]) > PRICE_BREAK_TOLERANCE:
        return "PRICE_BREAK"
    if row["quantity"] != row["quantity_confirm"]:
        return "QTY_BREAK"
    return "MATCHED"


def _build_output_frame(merged: pd.DataFrame) -> pd.DataFrame:
    """Project the reconciled trades onto the required output schema.

    Args:
        merged: The reconciled DataFrame, including a ``recon_status`` column.

    Returns:
        A DataFrame with exactly :data:`OUTPUT_COLUMNS`, dates formatted as
        ``MM/DD/YYYY``.
    """
    out = pd.DataFrame(
        {
            "TRADE_ID": merged["trade_id"],
            "ACCT_NUM": merged["account"],
            "TICKER": merged["ticker"],
            "SIDE": merged["side"],
            "QTY": merged["quantity"],
            "PRICE": merged["price"],
            "GROSS_AMT": merged["gross_amount"],
            "NET_AMT": merged["net_amount"],
            "COMMISSION": merged["commission"],
            "TRADE_DATE": merged["trade_date"].dt.strftime(DATE_FORMAT),
            "SETTLE_DATE": merged["settle_date"].dt.strftime(DATE_FORMAT),
            "BROKER": merged["broker"],
            "STATUS": merged["status"],
            "RECON_STATUS": merged["recon_status"],
        }
    )
    return out[OUTPUT_COLUMNS]


def _write_report(out: pd.DataFrame, output_path: Path) -> None:
    """Write the processed-trades report CSV.

    Args:
        out: The output DataFrame (already in the required schema/order).
        output_path: Destination CSV path.
    """
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        out.to_csv(handle, index=False)
    logger.info("Wrote %d processed trades to %s", len(out), output_path)


def _write_error_log(errors: pd.DataFrame, error_path: Path) -> None:
    """Write the validation error log.

    Args:
        errors: The error DataFrame from :func:`validate_trades` (includes an
            ``error_reason`` column).
        error_path: Destination CSV path.
    """
    with error_path.open("w", newline="", encoding="utf-8") as handle:
        if errors.empty:
            handle.write("trade_id,error_reason\n")
        else:
            cols = [c for c in ["trade_id", "error_reason"] if c in errors]
            errors[cols].to_csv(handle, index=False)
    logger.info("Wrote %d error rows to %s", len(errors), error_path)


def process_trades(run_date: str, config_path: Path) -> ProcessingResult:
    """Run the full daily trade pipeline for ``run_date``.

    Implements the shared pipeline: load config, load + validate trades,
    enrich (gross/net amounts, T+2 settlement), load broker confirms,
    reconcile via a left merge, write the report and error log, and return a
    populated :class:`ProcessingResult`.

    Args:
        run_date: The processing date as ``YYYYMMDD`` (e.g. ``"20240115"``).
        config_path: Path to ``batch_config.ini``.

    Returns:
        A :class:`ProcessingResult` with all six summary fields populated.
    """
    cfg = config.load_config(config_path)

    trade_file = _resolve_input_file(
        cfg["trade_input"], f"daily_trades_{run_date}.csv", run_date
    )
    confirm_file = _resolve_input_file(
        cfg["trade_input"], "counterparty_confirms.dat", run_date
    )

    trades = parsers.load_trades_csv(trade_file)
    total_loaded = len(trades)
    logger.info("Loaded %d raw trades from %s", total_loaded, trade_file)

    valid, errors = validation.validate_trades(trades)

    if errors.empty:
        reasons = pd.Series(dtype="string")
    else:
        reasons = errors["error_reason"].astype("string")

    duplicates_removed = int((reasons == "DUPLICATE").sum())
    # Every non-duplicate error row counts as a validation error (matching the
    # legacy script, which treats a non-whitelisted broker as an error too).
    validation_errors = len(errors) - duplicates_removed

    enriched = _enrich_trades(valid)

    confirms = parsers.load_counterparty_file(confirm_file)
    logger.info("Loaded %d counterparty confirms from %s", len(confirms), confirm_file)

    merged = enriched.merge(
        confirms, on="trade_id", how="left", suffixes=("", "_confirm")
    )
    merged["recon_status"] = merged.apply(_classify_recon, axis=1)

    status_counts = merged["recon_status"].value_counts()
    matched = int(status_counts.get("MATCHED", 0))
    breaks = int(
        status_counts.get("PRICE_BREAK", 0) + status_counts.get("QTY_BREAK", 0)
    )
    unmatched = int(status_counts.get("UNMATCHED", 0))

    output_dir = _resolve_output_dir(cfg["report_output"])
    _write_report(
        _build_output_frame(merged),
        output_dir / f"processed_trades_{run_date}.csv",
    )
    _write_error_log(errors, output_dir / f"trade_errors_{run_date}.txt")

    return ProcessingResult(
        total_loaded=total_loaded,
        duplicates_removed=duplicates_removed,
        validation_errors=validation_errors,
        matched=matched,
        breaks=breaks,
        unmatched=unmatched,
    )


def _configure_logging() -> None:
    """Configure root logging once for command-line runs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to ``sys.argv``).

    Returns:
        The parsed arguments namespace with ``date`` and ``config``.
    """
    parser = argparse.ArgumentParser(
        description="Option A: Pandas + Pydantic daily trade processor."
    )
    parser.add_argument(
        "--date",
        default="20240115",
        help="Run date as YYYYMMDD (default: 20240115).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/batch_config.ini"),
        help="Path to batch_config.ini (default: config/batch_config.ini).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> ProcessingResult:
    """CLI entry point: run the pipeline and log the summary.

    Args:
        argv: Optional argument list (defaults to ``sys.argv``).

    Returns:
        The :class:`ProcessingResult` produced by the run.
    """
    _configure_logging()
    args = _parse_args(argv)
    result = process_trades(args.date, args.config)
    logger.info(
        "ProcessingResult: total_loaded=%d, duplicates_removed=%d, "
        "validation_errors=%d, matched=%d, breaks=%d, unmatched=%d",
        result.total_loaded,
        result.duplicates_removed,
        result.validation_errors,
        result.matched,
        result.breaks,
        result.unmatched,
    )
    return result


if __name__ == "__main__":
    main()
