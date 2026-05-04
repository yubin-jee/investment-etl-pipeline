#!/usr/bin/env python
"""
Benchmark Comparison
Runs all three modernized implementations and the original legacy code,
verifies output equivalence, then benchmarks each over 10 iterations.
"""

import glob
import importlib.util
import os
import statistics
import sys
import time
import tracemalloc

# ---------------------------------------------------------------------------
# Imports — sibling modules + legacy script
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, parent_dir)

import trade_processor_pandas as tp_pandas  # noqa: E402
import trade_processor_polars as tp_polars  # noqa: E402
import trade_processor_duckdb as tp_duckdb  # noqa: E402

# Import legacy module without executing its __main__ block
_legacy_path = os.path.join(parent_dir, "legacy_scripts", "process_trades.py")
_spec = importlib.util.spec_from_file_location("process_trades_legacy", _legacy_path)
legacy_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy_mod)

import polars as pl  # noqa: E402
import pandas as pd  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_csv_files():
    trade_dir = os.path.join(parent_dir, "legacy_data", "trades")
    files = sorted(glob.glob(os.path.join(trade_dir, "daily_trades_*.csv")))
    if not files:
        print("ERROR: No trade CSV files found in", trade_dir)
        sys.exit(1)
    return files


def _run_original(csv_files):
    """Run the original legacy code and return (set_of_trade_ids, stats)."""
    legacy_mod.all_trades = []
    legacy_mod.error_count = 0
    legacy_mod.duplicate_count = 0
    legacy_mod.processed_ids = []

    for f in csv_files:
        legacy_mod.load_trades(f)
    legacy_mod.validate_trades()

    trade_ids = {t["trade_id"] for t in legacy_mod.all_trades}
    return trade_ids, {
        "valid": len(legacy_mod.all_trades),
        "errors": legacy_mod.error_count,
        "duplicates": legacy_mod.duplicate_count,
    }


def _run_pandas(csv_files):
    total_load_errors = 0
    dfs = []
    for f in csv_files:
        df, errs = tp_pandas.load_trades(f)
        dfs.append(df)
        total_load_errors += errs
    combined = pd.concat(dfs, ignore_index=True)
    valid_df, stats = tp_pandas.validate_trades(combined)
    stats["errors"] += total_load_errors
    return set(valid_df["trade_id"]), stats


def _run_polars(csv_files):
    total_load_errors = 0
    dfs = []
    for f in csv_files:
        df, errs = tp_polars.load_trades(f)
        dfs.append(df)
        total_load_errors += errs
    combined = pl.concat(dfs)
    valid_df, stats = tp_polars.validate_trades(combined)
    stats["errors"] += total_load_errors
    return set(valid_df["trade_id"].to_list()), stats


def _run_duckdb(csv_files):
    total_load_errors = 0
    dfs = []
    for f in csv_files:
        df, errs = tp_duckdb.load_trades(f)
        dfs.append(df)
        total_load_errors += errs
    combined = pd.concat(dfs, ignore_index=True)
    valid_df, stats = tp_duckdb.validate_trades(combined)
    stats["errors"] += total_load_errors
    return set(valid_df["trade_id"]), stats


# ---------------------------------------------------------------------------
# Correctness verification
# ---------------------------------------------------------------------------
def verify_correctness(csv_files):
    print("=" * 60)
    print("CORRECTNESS VERIFICATION")
    print("=" * 60)

    orig_ids, orig_stats = _run_original(csv_files)
    pandas_ids, pandas_stats = _run_pandas(csv_files)
    polars_ids, polars_stats = _run_polars(csv_files)
    duckdb_ids, duckdb_stats = _run_duckdb(csv_files)

    all_match = orig_ids == pandas_ids == polars_ids == duckdb_ids
    print(f"\nOriginal valid trade IDs ({len(orig_ids)}): {sorted(orig_ids)}")
    print(f"Pandas   valid trade IDs ({len(pandas_ids)}): {sorted(pandas_ids)}")
    print(f"Polars   valid trade IDs ({len(polars_ids)}): {sorted(polars_ids)}")
    print(f"DuckDB   valid trade IDs ({len(duckdb_ids)}): {sorted(duckdb_ids)}")

    if all_match:
        print("\nAll implementations produce IDENTICAL valid trade ID sets.")
    else:
        print("\nMISMATCH detected!")
        for name, ids in [
            ("Pandas", pandas_ids),
            ("Polars", polars_ids),
            ("DuckDB", duckdb_ids),
        ]:
            extra = ids - orig_ids
            missing = orig_ids - ids
            if extra:
                print(f"  {name} extra:   {sorted(extra)}")
            if missing:
                print(f"  {name} missing: {sorted(missing)}")
        sys.exit(1)

    # Verify stat counts match
    print("\nStats comparison:")
    print(f"  {'':>10} | {'valid':>6} | {'errors':>6} | {'dupes':>6}")
    for name, s in [
        ("Original", orig_stats),
        ("Pandas", pandas_stats),
        ("Polars", polars_stats),
        ("DuckDB", duckdb_stats),
    ]:
        print(f"  {name:>10} | {s['valid']:>6} | {s['errors']:>6} | {s['duplicates']:>6}")

    assert orig_stats["valid"] == pandas_stats["valid"] == polars_stats["valid"] == duckdb_stats["valid"], \
        "Valid trade counts do not match!"
    assert orig_stats["errors"] == pandas_stats["errors"] == polars_stats["errors"] == duckdb_stats["errors"], \
        "Error counts do not match!"
    assert orig_stats["duplicates"] == pandas_stats["duplicates"] == polars_stats["duplicates"] == duckdb_stats["duplicates"], \
        "Duplicate counts do not match!"

    print("All stats match.\n")


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------
def benchmark(name, run_fn, csv_files, n=10):
    times = []
    memories = []
    last_stats = None

    for _ in range(n):
        tracemalloc.start()
        t0 = time.perf_counter()
        _, stats = run_fn(csv_files)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        times.append(elapsed_ms)
        memories.append(peak / (1024 * 1024))
        last_stats = stats

    return {
        "name": name,
        "median_time_ms": statistics.median(times),
        "peak_memory_mb": max(memories),
        **last_stats,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    csv_files = _find_csv_files()
    print(f"Trade files: {csv_files}\n")

    # 1. Verify correctness
    verify_correctness(csv_files)

    # 2. Benchmark
    print("=" * 60)
    print("BENCHMARK (10 iterations each)")
    print("=" * 60)

    results = [
        benchmark("Original", _run_original, csv_files),
        benchmark("Pandas", _run_pandas, csv_files),
        benchmark("Polars", _run_polars, csv_files),
        benchmark("DuckDB", _run_duckdb, csv_files),
    ]

    # 3. Print comparison table
    header = f"{'Framework':<12} | {'Median ms':>10} | {'Peak MB':>10} | {'Valid':>6} | {'Errors':>6} | {'Dupes':>6}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['name']:<12} | {r['median_time_ms']:>10.2f} | "
            f"{r['peak_memory_mb']:>10.4f} | {r['valid']:>6} | "
            f"{r['errors']:>6} | {r['duplicates']:>6}"
        )

    # 4. Recommendation
    fastest = min(results, key=lambda r: r["median_time_ms"])
    lightest = min(results, key=lambda r: r["peak_memory_mb"])

    print(f"\nRecommendation:")
    print(f"  Fastest:       {fastest['name']} ({fastest['median_time_ms']:.2f} ms)")
    print(f"  Lowest memory: {lightest['name']} ({lightest['peak_memory_mb']:.4f} MB)")
    if fastest["name"] == lightest["name"]:
        print(f"  {fastest['name']} wins on both speed and memory.")
    else:
        print(
            f"  Choose {fastest['name']} for speed or "
            f"{lightest['name']} for memory efficiency."
        )
