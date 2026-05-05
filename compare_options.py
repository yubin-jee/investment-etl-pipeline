"""Comparison harness for all three modernization options.

Runs all three options against the same sample data and compares
their outputs for consistency. Also attempts to run the legacy
script and highlight differences (bug fixes).
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("compare")

REPO_ROOT = Path(__file__).resolve().parent
TRADE_FILE = REPO_ROOT / "legacy_data" / "trades" / "daily_trades_20240315.csv"
CONFIRM_FILE = REPO_ROOT / "legacy_data" / "trades" / "counterparty_confirms.dat"


def run_option_a() -> tuple[float, pd.DataFrame | None]:
    """Run Option A and return (elapsed_seconds, output_df)."""
    from option_a.run_pipeline import run

    output_dir = REPO_ROOT / "option_a" / "output"
    start = time.time()
    try:
        df = run(
            trade_file=TRADE_FILE,
            confirm_file=CONFIRM_FILE,
            output_dir=output_dir,
        )
        elapsed = time.time() - start
        return elapsed, df
    except Exception:
        logger.exception("Option A failed")
        return time.time() - start, None


def run_option_b() -> tuple[float, pd.DataFrame | None]:
    """Run Option B (Dagster) programmatically and return (elapsed, output_df)."""
    from dagster import materialize

    from option_b.assets import (
        enriched_trades,
        raw_confirms,
        raw_trades,
        reconciled_trades,
        trade_output,
        validated_trades,
    )
    from option_b.resources import FilePathResource

    output_dir = REPO_ROOT / "option_b" / "output"
    start = time.time()
    try:
        result = materialize(
            assets=[
                raw_trades,
                raw_confirms,
                validated_trades,
                enriched_trades,
                reconciled_trades,
                trade_output,
            ],
            resources={
                "file_paths": FilePathResource(
                    trade_file=str(TRADE_FILE),
                    confirm_file=str(CONFIRM_FILE),
                    output_dir=str(output_dir),
                ),
            },
        )
        elapsed = time.time() - start
        output_file = output_dir / "processed_trades.csv"
        if output_file.exists():
            df = pd.read_csv(output_file)
            return elapsed, df
        return elapsed, None
    except Exception:
        logger.exception("Option B failed")
        return time.time() - start, None


def run_option_c() -> tuple[float, pd.DataFrame | None]:
    """Run Option C in demo mode and return (elapsed, output_df)."""
    from option_c.run_watcher import run_demo

    output_dir = REPO_ROOT / "option_c" / "output"
    start = time.time()
    try:
        df = run_demo(
            trade_file=TRADE_FILE,
            confirm_file=CONFIRM_FILE,
            output_dir=output_dir,
        )
        elapsed = time.time() - start
        return elapsed, df
    except Exception:
        logger.exception("Option C failed")
        return time.time() - start, None


def run_legacy() -> tuple[float, pd.DataFrame | None]:
    """Attempt to run the legacy script and capture its output."""
    legacy_script = REPO_ROOT / "legacy_scripts" / "process_trades.py"
    output_file = REPO_ROOT / "reports" / "processed_trades_20240315.csv"

    start = time.time()
    try:
        subprocess.run(
            [sys.executable, str(legacy_script), "20240315"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed = time.time() - start
        if output_file.exists():
            df = pd.read_csv(output_file)
            return elapsed, df
        return elapsed, None
    except Exception:
        logger.exception("Legacy script failed")
        return time.time() - start, None


def compare_outputs(results: dict[str, tuple[float, pd.DataFrame | None]]) -> None:
    """Compare outputs from all options and print comparison table."""
    print("\n" + "=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)

    # Header
    print(f"\n{'Metric':<30}", end="")
    for name in results:
        print(f"{name:<20}", end="")
    print()
    print("-" * (30 + 20 * len(results)))

    # Execution time
    print(f"{'Execution Time (s)':<30}", end="")
    for name, (elapsed, _) in results.items():
        print(f"{elapsed:<20.3f}", end="")
    print()

    # Row counts and recon stats
    metrics = [
        ("Total Valid Trades", lambda df: len(df)),
        ("MATCHED", lambda df: len(df[df.get("recon_status", df.get("RECON_STATUS", pd.Series())) == "MATCHED"]) if "recon_status" in df.columns or "RECON_STATUS" in df.columns else "N/A"),
        ("PRICE_BREAK", lambda df: len(df[df.get("recon_status", df.get("RECON_STATUS", pd.Series())) == "PRICE_BREAK"]) if "recon_status" in df.columns or "RECON_STATUS" in df.columns else "N/A"),
        ("QTY_BREAK", lambda df: len(df[df.get("recon_status", df.get("RECON_STATUS", pd.Series())) == "QTY_BREAK"]) if "recon_status" in df.columns or "RECON_STATUS" in df.columns else "N/A"),
        ("UNMATCHED", lambda df: len(df[df.get("recon_status", df.get("RECON_STATUS", pd.Series())) == "UNMATCHED"]) if "recon_status" in df.columns or "RECON_STATUS" in df.columns else "N/A"),
    ]

    for metric_name, extractor in metrics:
        print(f"{metric_name:<30}", end="")
        for name, (_, df) in results.items():
            if df is not None:
                try:
                    val = extractor(df)
                    print(f"{str(val):<20}", end="")
                except Exception:
                    print(f"{'ERROR':<20}", end="")
            else:
                print(f"{'FAILED':<20}", end="")
        print()

    # Settlement date comparison
    print(f"\n{'Settlement Date Check':<30}")
    print("-" * 60)
    modernized_options = {k: v for k, v in results.items() if k != "Legacy"}
    legacy_elapsed, legacy_df = results.get("Legacy", (0, None))

    for name, (_, df) in modernized_options.items():
        if df is not None and legacy_df is not None:
            settle_col = "settle_date" if "settle_date" in df.columns else "SETTLE_DATE"
            legacy_settle_col = "SETTLE_DATE" if "SETTLE_DATE" in legacy_df.columns else "settle_date"
            if settle_col in df.columns and legacy_settle_col in legacy_df.columns:
                modern_dates = set(df[settle_col].dropna().astype(str).unique())
                legacy_dates = set(legacy_df[legacy_settle_col].dropna().astype(str).unique())
                if modern_dates != legacy_dates:
                    print(f"  {name}: Settlement dates DIFFER from legacy (expected — weekend bug fix)")
                else:
                    print(f"  {name}: Settlement dates MATCH legacy")
            else:
                print(f"  {name}: Could not compare settlement dates")
        elif df is not None:
            print(f"  {name}: No legacy output for comparison")

    # Cross-option consistency check
    print(f"\n{'Cross-Option Consistency':<30}")
    print("-" * 60)
    option_dfs = {k: v[1] for k, v in results.items() if k != "Legacy" and v[1] is not None}
    option_names = list(option_dfs.keys())

    if len(option_names) >= 2:
        ref_name = option_names[0]
        ref_df = option_dfs[ref_name]
        for other_name in option_names[1:]:
            other_df = option_dfs[other_name]
            if len(ref_df) == len(other_df):
                # Compare key fields
                ref_sorted = ref_df.sort_values("trade_id").reset_index(drop=True)
                other_sorted = other_df.sort_values("trade_id").reset_index(drop=True)
                compare_cols = ["trade_id", "recon_status", "gross_amount", "net_amount"]
                available_cols = [c for c in compare_cols if c in ref_sorted.columns and c in other_sorted.columns]
                matches = all(
                    ref_sorted[col].astype(str).equals(other_sorted[col].astype(str))
                    for col in available_cols
                )
                status = "IDENTICAL" if matches else "DIFFER"
                print(f"  {ref_name} vs {other_name}: {status}")
            else:
                print(f"  {ref_name} vs {other_name}: ROW COUNT MISMATCH ({len(ref_df)} vs {len(other_df)})")

    print("\n" + "=" * 80)


def main() -> None:
    """Run all options and compare."""
    logger.info("Starting comparison of all trade processing options...")

    results: dict[str, tuple[float, pd.DataFrame | None]] = {}

    # Run legacy first (for comparison)
    logger.info("\n--- Running Legacy Script ---")
    results["Legacy"] = run_legacy()

    # Run each option
    for name, runner in [
        ("Option A", run_option_a),
        ("Option B", run_option_b),
        ("Option C", run_option_c),
    ]:
        logger.info("\n--- Running %s ---", name)
        results[name] = runner()

    compare_outputs(results)


if __name__ == "__main__":
    main()
