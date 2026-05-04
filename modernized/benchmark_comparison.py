#!/usr/bin/env python
"""
Benchmark Comparison — Legacy vs Pandas vs Polars vs DuckDB trade processing.

Runs each implementation 10 times, collects median execution time and peak memory,
verifies output equivalence, and prints a comparison table with a recommendation.
"""

import glob
import os
import statistics
import sys
import time
import tracemalloc

import pandas as pd
import polars as pl

# ---------------------------------------------------------------------------
# Imports for each implementation
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modernized.trade_processor_pandas import (
    load_trades as pandas_load,
    validate_trades as pandas_validate,
)
from modernized.trade_processor_polars import (
    load_trades as polars_load,
    validate_trades as polars_validate,
)
from modernized.trade_processor_duckdb import (
    load_trades as duckdb_load,
    validate_trades as duckdb_validate,
)

# ---------------------------------------------------------------------------
# Legacy runner (adapted to work outside Windows paths)
# ---------------------------------------------------------------------------

def run_legacy(csv_files: list[str]) -> tuple[float, float, dict]:
    """Run the original load_trades + validate_trades and return (time_ms, peak_mb, stats)."""
    import importlib
    spec = importlib.util.spec_from_file_location(
        "process_trades",
        os.path.join(os.path.dirname(__file__), "..", "legacy_scripts", "process_trades.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    # Reset mutable global state before each run
    mod.all_trades = []
    mod.error_count = 0
    mod.duplicate_count = 0
    mod.processed_ids = []

    spec.loader.exec_module(mod)

    # Reset again after exec_module (which sets defaults)
    mod.all_trades = []
    mod.error_count = 0
    mod.duplicate_count = 0
    mod.processed_ids = []

    tracemalloc.start()
    start = time.perf_counter()

    for f in csv_files:
        mod.load_trades(f)
    mod.validate_trades()

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    valid_ids = sorted([t["trade_id"] for t in mod.all_trades])
    stats = {
        "valid": len(mod.all_trades),
        "errors": mod.error_count,
        "duplicates": mod.duplicate_count,
        "valid_ids": valid_ids,
    }
    return elapsed_ms, peak / 1024 / 1024, stats


def run_pandas(csv_files: list[str]) -> tuple[float, float, dict]:
    """Run the pandas implementation and return (time_ms, peak_mb, stats)."""
    tracemalloc.start()
    start = time.perf_counter()

    all_df = pd.DataFrame()
    for f in csv_files:
        all_df = pd.concat([all_df, pandas_load(f)], ignore_index=True)
    df, stats = pandas_validate(all_df)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats["valid_ids"] = sorted(df["trade_id"].tolist())
    return elapsed_ms, peak / 1024 / 1024, stats


def run_polars(csv_files: list[str]) -> tuple[float, float, dict]:
    """Run the polars implementation and return (time_ms, peak_mb, stats)."""
    tracemalloc.start()
    start = time.perf_counter()

    frames = [polars_load(f) for f in csv_files]
    all_df = pl.concat(frames)
    df, stats = polars_validate(all_df)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats["valid_ids"] = sorted(df["trade_id"].to_list())
    return elapsed_ms, peak / 1024 / 1024, stats


def run_duckdb(csv_files: list[str]) -> tuple[float, float, dict]:
    """Run the DuckDB implementation and return (time_ms, peak_mb, stats)."""
    tracemalloc.start()
    start = time.perf_counter()

    frames = [duckdb_load(f) for f in csv_files]
    all_df = pd.concat(frames, ignore_index=True)
    df, stats = duckdb_validate(all_df)

    elapsed_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats["valid_ids"] = sorted(df["trade_id"].tolist())
    return elapsed_ms, peak / 1024 / 1024, stats


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

ITERATIONS = 10
RUNNERS = {
    "Legacy (csv)": run_legacy,
    "Pandas": run_pandas,
    "Polars": run_polars,
    "DuckDB": run_duckdb,
}


def main() -> None:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "legacy_data", "trades")
    csv_files = sorted(glob.glob(os.path.join(base_dir, "daily_trades_*.csv")))

    if not csv_files:
        print("No trade files found!")
        sys.exit(1)

    print(f"Trade files: {csv_files}")
    print(f"Running each implementation {ITERATIONS} times...\n")

    results: dict[str, dict] = {}
    reference_ids: list[str] | None = None

    for name, runner in RUNNERS.items():
        times: list[float] = []
        mems: list[float] = []
        last_stats: dict = {}

        for i in range(ITERATIONS):
            t, m, stats = runner(csv_files)
            times.append(t)
            mems.append(m)
            last_stats = stats

        # Correctness check against reference (legacy)
        if reference_ids is None:
            reference_ids = last_stats["valid_ids"]
        else:
            assert last_stats["valid_ids"] == reference_ids, (
                f"Output mismatch for {name}!\n"
                f"  Expected IDs: {reference_ids}\n"
                f"  Got IDs:      {last_stats['valid_ids']}"
            )

        results[name] = {
            "median_time_ms": statistics.median(times),
            "peak_memory_mb": max(mems),
            "valid": last_stats["valid"],
            "errors": last_stats["errors"],
            "duplicates": last_stats["duplicates"],
        }

    # --- Print comparison table ---
    print("\n" + "=" * 90)
    print("BENCHMARK COMPARISON")
    print("=" * 90)

    header = f"{'Framework':<16} | {'Median Time (ms)':>17} | {'Peak Mem (MB)':>14} | {'Valid':>6} | {'Errors':>6} | {'Dupes':>6}"
    print(header)
    print("-" * len(header))

    for name, r in results.items():
        print(
            f"{name:<16} | {r['median_time_ms']:>17.2f} | {r['peak_memory_mb']:>14.2f} | "
            f"{r['valid']:>6} | {r['errors']:>6} | {r['duplicates']:>6}"
        )

    print("-" * len(header))

    # Correctness confirmation
    print("\nCorrectness: All implementations produce identical valid trade IDs.")

    # Recommendation
    fastest = min(results, key=lambda k: results[k]["median_time_ms"])
    lowest_mem = min(results, key=lambda k: results[k]["peak_memory_mb"])

    print(f"\nRecommendation:")
    print(f"  Fastest:        {fastest} ({results[fastest]['median_time_ms']:.2f} ms)")
    print(f"  Lowest memory:  {lowest_mem} ({results[lowest_mem]['peak_memory_mb']:.2f} MB)")

    if fastest == lowest_mem:
        print(f"\n  -> {fastest} wins on both speed and memory. Recommended for production use.")
    else:
        print(f"\n  -> For speed-critical workloads, use {fastest}.")
        print(f"  -> For memory-constrained environments, use {lowest_mem}.")
        # General recommendation
        print(f"  -> For a balanced choice, Polars is recommended as it typically offers")
        print(f"     the best combination of speed, memory efficiency, and ergonomic API.")


if __name__ == "__main__":
    main()
