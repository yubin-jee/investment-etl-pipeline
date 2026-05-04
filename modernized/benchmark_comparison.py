"""Benchmark Comparison - Legacy vs Pandas vs Polars vs DuckDB"""

import glob
import statistics
import time
import tracemalloc

import legacy_scripts.process_trades as legacy
import modernized.trade_processor_pandas as tp_pandas
import modernized.trade_processor_polars as tp_polars
import modernized.trade_processor_duckdb as tp_duckdb


def run_legacy(files):
    legacy.all_trades = []
    legacy.error_count = 0
    legacy.duplicate_count = 0
    legacy.processed_ids = []
    for f in files:
        legacy.load_trades(f)
    legacy.validate_trades()
    return (
        [t["trade_id"] for t in legacy.all_trades],
        len(legacy.all_trades),
        legacy.error_count,
        legacy.duplicate_count,
    )


def run_pandas(files):
    import pandas as pd

    frames = [tp_pandas.load_trades(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = tp_pandas.validate_trades(df)
    return list(df["trade_id"])


def run_polars(files):
    import polars as pl

    frames = [tp_polars.load_trades(f) for f in files]
    df = pl.concat(frames)
    df = tp_polars.validate_trades(df)
    return list(df["trade_id"])


def run_duckdb(files):
    relations = [tp_duckdb.load_trades(f) for f in files]
    combined = relations[0]
    for r in relations[1:]:
        combined = combined.union(r)
    result = tp_duckdb.validate_trades(combined)
    result_df = result.df()
    return list(result_df["trade_id"])


def verify_correctness(files):
    print("=" * 60)
    print("CORRECTNESS VERIFICATION")
    print("=" * 60)

    legacy_ids, _, _, _ = run_legacy(files)
    baseline = set(legacy_ids)
    print(f"Legacy baseline: {len(baseline)} valid trade IDs")

    pandas_ids = set(run_pandas(files))
    polars_ids = set(run_polars(files))
    duckdb_ids = set(run_duckdb(files))

    assert pandas_ids == baseline, (
        f"Pandas mismatch: extra={pandas_ids - baseline}, missing={baseline - pandas_ids}"
    )
    assert polars_ids == baseline, (
        f"Polars mismatch: extra={polars_ids - baseline}, missing={baseline - polars_ids}"
    )
    assert duckdb_ids == baseline, (
        f"DuckDB mismatch: extra={duckdb_ids - baseline}, missing={baseline - duckdb_ids}"
    )
    print("All implementations produce identical trade ID sets.\n")


def benchmark(name, run_fn, files, iterations=10):
    times = []
    peaks = []
    valid_count = 0
    error_count = 0
    dup_count = 0

    for _ in range(iterations):
        tracemalloc.start()
        start = time.perf_counter()

        if name == "Legacy":
            ids, valid_count, error_count, dup_count = run_fn(files)
        else:
            ids = run_fn(files)
            valid_count = len(ids)

        elapsed_ms = (time.perf_counter() - start) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        times.append(elapsed_ms)
        peaks.append(peak / 1024 / 1024)

    return {
        "name": name,
        "median_time": statistics.median(times),
        "peak_memory": max(peaks),
        "valid": valid_count,
        "errors": error_count,
        "duplicates": dup_count,
    }


def main():
    files = sorted(glob.glob("legacy_data/trades/daily_trades_*.csv"))
    if not files:
        print("ERROR: No trade files found")
        return

    print(f"Found {len(files)} trade files\n")

    verify_correctness(files)

    print("=" * 60)
    print("BENCHMARK (10 iterations each)")
    print("=" * 60)

    results = [
        benchmark("Legacy", run_legacy, files),
        benchmark("Pandas", lambda f: run_pandas(f), files),
        benchmark("Polars", lambda f: run_polars(f), files),
        benchmark("DuckDB", lambda f: run_duckdb(f), files),
    ]

    header = f"{'Framework':<12} | {'Median Time (ms)':>17} | {'Peak Memory (MB)':>17} | {'Valid Trades':>12} | {'Errors':>7} | {'Duplicates':>10}"
    print(header)
    print("-" * len(header))

    for r in results:
        print(
            f"{r['name']:<12} | {r['median_time']:>17.2f} | {r['peak_memory']:>17.2f} | {r['valid']:>12} | {r['errors']:>7} | {r['duplicates']:>10}"
        )

    fastest = min(results, key=lambda r: r["median_time"])
    lowest_mem = min(results, key=lambda r: r["peak_memory"])

    print(f"\nRecommendation: {fastest['name']} is fastest ({fastest['median_time']:.2f} ms), "
          f"{lowest_mem['name']} uses least memory ({lowest_mem['peak_memory']:.2f} MB).")

    modern = [r for r in results if r["name"] != "Legacy"]
    best = min(modern, key=lambda r: r["median_time"] + r["peak_memory"])
    if best["name"] != fastest["name"] or best["name"] != lowest_mem["name"]:
        print(f"{best['name']} recommended for best speed/memory tradeoff.")


if __name__ == "__main__":
    main()
