#!/usr/bin/env python
"""Benchmark harness comparing pandas, polars, and DuckDB trade ingestion.

Measures wall-clock time and peak memory for ``load_trades`` and
``validate_trades`` across all three implementations, then asserts that the
cleaned outputs are equivalent.

Usage::

    python benchmark_ingest.py [csv_path ...]

If no paths are given the script auto-discovers CSV files under
``legacy_data/trades/``.
"""

from __future__ import annotations

import glob
import os
import sys
import time
import tracemalloc
from typing import Any, Callable

import pandas as pd


def _discover_csv_files() -> list[str]:
    """Return paths to daily trade CSV files in the repository."""
    base = os.path.join(os.path.dirname(__file__), "legacy_data", "trades")
    files = sorted(glob.glob(os.path.join(base, "daily_trades_*.csv")))
    if not files:
        sys.exit(f"No trade CSV files found under {base}")
    return files


def _measure(func: Callable[..., Any], *args: Any) -> tuple[Any, float, int]:
    """Run *func* and return ``(result, elapsed_seconds, peak_memory_bytes)``."""
    tracemalloc.start()
    start = time.perf_counter()
    result = func(*args)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak


def _to_pandas(df: Any) -> pd.DataFrame:
    """Coerce a polars or pandas DataFrame to pandas for comparison."""
    try:
        import polars as pl

        if isinstance(df, pl.DataFrame):
            return df.to_pandas()
    except ImportError:
        pass
    return df


def run_benchmark(csv_files: list[str]) -> None:
    """Execute the benchmark for all three implementations."""
    from ingest import ingest_duckdb, ingest_pandas, ingest_polars

    implementations: list[tuple[str, Any]] = [
        ("pandas", ingest_pandas),
        ("polars", ingest_polars),
        ("duckdb", ingest_duckdb),
    ]

    header = (
        f"{'Framework':<10} {'Load(s)':>8} {'Valid(s)':>9} {'Total(s)':>9} "
        f"{'PeakMem':>10} {'Accepted':>9} {'Rejected':>9}"
    )

    print("=" * len(header))
    print("Trade Ingestion Benchmark")
    print(f"Files: {csv_files}")
    print("=" * len(header))
    print()

    results: dict[str, pd.DataFrame] = {}

    for name, module in implementations:
        total_load = 0.0
        total_valid = 0.0
        total_peak = 0
        total_accepted = 0
        total_rejected = 0
        clean_frames: list[pd.DataFrame] = []

        for csv_file in csv_files:
            raw, load_time, load_mem = _measure(module.load_trades, csv_file)
            (clean, rejected), valid_time, valid_mem = _measure(
                module.validate_trades, raw
            )

            total_load += load_time
            total_valid += valid_time
            total_peak = max(total_peak, load_mem, valid_mem)

            clean_pd = _to_pandas(clean)
            rejected_pd = _to_pandas(rejected)

            total_accepted += len(clean_pd)
            total_rejected += len(rejected_pd)
            clean_frames.append(clean_pd)

        combined = pd.concat(clean_frames, ignore_index=True)
        results[name] = combined

        peak_mb = total_peak / (1024 * 1024)
        total_time = total_load + total_valid
        print(
            f"{name:<10} {total_load:>8.4f} {total_valid:>9.4f} {total_time:>9.4f} "
            f"{peak_mb:>9.2f}M {total_accepted:>9} {total_rejected:>9}"
        )

    print()

    # Assert consistency across all three implementations.
    ref_name, ref_df = "pandas", results["pandas"]
    for name, df in results.items():
        if name == ref_name:
            continue
        assert len(df) == len(ref_df), (
            f"Row count mismatch: {ref_name}={len(ref_df)}, {name}={len(df)}"
        )

        # Sort both by trade_id for stable comparison.
        ref_sorted = ref_df.sort_values("trade_id").reset_index(drop=True)
        other_sorted = df.sort_values("trade_id").reset_index(drop=True)

        # Compare key columns (dates may differ in dtype so compare as str).
        for col in ["trade_id", "account", "ticker", "side", "broker", "status"]:
            pd.testing.assert_series_equal(
                ref_sorted[col].astype(str),
                other_sorted[col].astype(str),
                check_names=False,
                obj=f"{ref_name}.{col} vs {name}.{col}",
            )
        for col in ["quantity", "price", "commission"]:
            pd.testing.assert_series_equal(
                ref_sorted[col].astype(float),
                other_sorted[col].astype(float),
                check_names=False,
                obj=f"{ref_name}.{col} vs {name}.{col}",
            )

    print(header)
    print("All implementations produce identical cleaned output.")


if __name__ == "__main__":
    csv_files = sys.argv[1:] or _discover_csv_files()
    run_benchmark(csv_files)
