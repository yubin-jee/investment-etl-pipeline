"""Comparison harness — runs all three modernized options (and the legacy
processor) against the same sample data and produces a side-by-side report.

Usage:
    python -m modernized.compare [--date 20240315]

Outputs:
    - Formatted comparison table to stdout
    - Full report at reports/modernization_comparison.md
"""

from __future__ import annotations

import csv
import io
import logging
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_lines(directory: Path) -> int:
    """Count total lines of Python code in a directory."""
    total = 0
    for f in directory.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        with open(f) as fh:
            total += sum(1 for _ in fh)
    return total


def _count_files(directory: Path) -> int:
    return sum(1 for f in directory.rglob("*.py") if "__pycache__" not in str(f))


def _recon_counts(df: pd.DataFrame) -> Dict[str, int]:
    """Count reconciliation statuses in a DataFrame."""
    col = None
    for candidate in ("recon_status", "RECON_STATUS"):
        if candidate in df.columns:
            col = candidate
            break
    if col is None:
        return {"MATCHED": 0, "PRICE_BREAK": 0, "QTY_BREAK": 0, "UNMATCHED": 0}
    counts = df[col].value_counts().to_dict()
    return {
        "MATCHED": counts.get("MATCHED", 0),
        "PRICE_BREAK": counts.get("PRICE_BREAK", 0),
        "QTY_BREAK": counts.get("QTY_BREAK", 0),
        "UNMATCHED": counts.get("UNMATCHED", 0),
    }


# ---------------------------------------------------------------------------
# Legacy runner
# ---------------------------------------------------------------------------

def run_legacy(trade_date: str) -> Dict[str, Any]:
    """Run legacy process_trades.py and capture its output."""
    legacy_script = PROJECT_ROOT / "legacy_scripts" / "process_trades.py"
    output_file = PROJECT_ROOT / "reports" / f"processed_trades_{trade_date}.csv"

    # Clean previous output
    if output_file.exists():
        output_file.unlink()

    start = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, str(legacy_script), trade_date],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.perf_counter() - start

        if output_file.exists():
            df = pd.read_csv(output_file, dtype=str)
        else:
            df = pd.DataFrame()

        return {
            "name": "Legacy",
            "elapsed": elapsed,
            "row_count": len(df),
            "recon": _recon_counts(df),
            "df": df,
            "returncode": result.returncode,
        }
    except Exception as exc:
        return {
            "name": "Legacy",
            "elapsed": time.perf_counter() - start,
            "row_count": 0,
            "recon": _recon_counts(pd.DataFrame()),
            "df": pd.DataFrame(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Modernized runners
# ---------------------------------------------------------------------------

def run_option_a(trade_date: str) -> Dict[str, Any]:
    """Run Option A: pandas + SQLAlchemy."""
    from modernized.option_a_pandas.process_trades import run as run_a

    output_dir = PROJECT_ROOT / "reports" / "option_a"
    start = time.perf_counter()
    df = run_a(trade_date, output_dir=str(output_dir))
    elapsed = time.perf_counter() - start
    return {
        "name": "Option A (pandas)",
        "elapsed": elapsed,
        "row_count": len(df),
        "recon": _recon_counts(df),
        "df": df,
    }


def run_option_b(trade_date: str) -> Dict[str, Any]:
    """Run Option B: Airflow tasks (standalone)."""
    from modernized.option_b_airflow.tasks.trade_tasks import run_pipeline

    output_dir = PROJECT_ROOT / "reports" / "option_b"
    start = time.perf_counter()
    df = run_pipeline(trade_date, output_dir=str(output_dir))
    elapsed = time.perf_counter() - start
    return {
        "name": "Option B (Airflow)",
        "elapsed": elapsed,
        "row_count": len(df),
        "recon": _recon_counts(df),
        "df": df,
    }


def run_option_c(trade_date: str) -> Dict[str, Any]:
    """Run Option C: Event-driven processor (direct invocation)."""
    from modernized.option_c_event_driven.processor import TradeProcessor

    trade_dir = PROJECT_ROOT / "legacy_data" / "trades"
    output_dir = PROJECT_ROOT / "reports" / "option_c"
    output_dir.mkdir(parents=True, exist_ok=True)

    processor = TradeProcessor(output_dir=str(output_dir))
    trade_file = trade_dir / f"daily_trades_{trade_date}.csv"
    confirm_file = trade_dir / "counterparty_confirms.dat"

    start = time.perf_counter()
    processor.receive_trade_file(trade_file)
    processor.receive_confirm_file(confirm_file)
    df = processor.try_process()
    elapsed = time.perf_counter() - start

    if df is None:
        df = pd.DataFrame()

    return {
        "name": "Option C (Event-Driven)",
        "elapsed": elapsed,
        "row_count": len(df),
        "recon": _recon_counts(df),
        "df": df,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

FEATURE_MATRIX = {
    "Error Handling": {
        "Legacy": "print() to stdout, global counter",
        "Option A": "Structured logging, error list returned",
        "Option B": "Airflow task-level retry + alerting",
        "Option C": "Dead-letter queue, per-file error handling",
    },
    "Idempotency": {
        "Legacy": "No — appends to global list, re-runs duplicate data",
        "Option A": "Yes — SQLAlchemy merge (upsert) by trade_id",
        "Option B": "Yes — task re-runs produce same result",
        "Option C": "Yes — content-hash deduplication",
    },
    "Testability": {
        "Legacy": "Difficult — global state, hardcoded paths, no functions return values",
        "Option A": "Good — pure functions, DI for paths/DB",
        "Option B": "Excellent — each task testable independently",
        "Option C": "Good — state machine with clear transitions",
    },
    "Scalability": {
        "Legacy": "Single-threaded, O(n*m) recon, in-memory only",
        "Option A": "Vectorized pandas, handles 100K+ trades",
        "Option B": "Horizontal via Airflow workers, parallelisable tasks",
        "Option C": "Async-capable, maps to serverless (Lambda/Functions)",
    },
    "Retry Support": {
        "Legacy": "None — manual re-run by ops",
        "Option A": "Manual re-run (idempotent)",
        "Option B": "Built-in retries with configurable delay",
        "Option C": "Automatic on file re-arrival",
    },
    "Monitoring": {
        "Legacy": "None (check stdout or error log file)",
        "Option A": "Python logging (configurable level)",
        "Option B": "Airflow UI, metrics, email alerting",
        "Option C": "Python logging, extensible to cloud monitoring",
    },
    "Portability": {
        "Legacy": "Windows-only (hardcoded C:\\ paths)",
        "Option A": "Cross-platform (env-var config)",
        "Option B": "Requires Airflow infrastructure",
        "Option C": "Cross-platform; maps to S3/Blob triggers",
    },
    "T+2 Calculation": {
        "Legacy": "Broken (ignores weekends, rough month-end)",
        "Option A": "Fixed (pandas BDay)",
        "Option B": "Fixed (pandas BDay via shared module)",
        "Option C": "Fixed (pandas BDay via shared module)",
    },
    "Reconciliation": {
        "Legacy": "O(n*m) nested loop",
        "Option A": "Hash-join O(n+m) via dict lookup",
        "Option B": "Hash-join O(n+m) via shared reconciler",
        "Option C": "Hash-join O(n+m) via shared reconciler",
    },
}


def generate_report(
    results: List[Dict[str, Any]],
    trade_date: str,
) -> str:
    """Generate a Markdown comparison report."""
    lines: List[str] = []
    lines.append("# Trade Processing Modernization — Comparison Report")
    lines.append(f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Trade Date**: {trade_date}")
    lines.append(f"**Input**: `legacy_data/trades/daily_trades_{trade_date}.csv` + `counterparty_confirms.dat`\n")

    # --- Correctness ---
    lines.append("## 1. Correctness Comparison\n")
    lines.append("| Metric | " + " | ".join(r["name"] for r in results) + " |")
    lines.append("|--------|" + "|".join("-----" for _ in results) + "|")
    lines.append("| Output rows | " + " | ".join(str(r["row_count"]) for r in results) + " |")
    for status in ("MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"):
        lines.append(
            f"| {status} | "
            + " | ".join(str(r["recon"].get(status, "N/A")) for r in results)
            + " |"
        )

    # --- Performance ---
    lines.append("\n## 2. Performance\n")
    lines.append("| Approach | Wall-Clock Time (s) |")
    lines.append("|----------|-------------------|")
    for r in results:
        lines.append(f"| {r['name']} | {r['elapsed']:.4f} |")

    # --- Code Metrics ---
    lines.append("\n## 3. Code Metrics\n")
    dirs = {
        "Legacy": PROJECT_ROOT / "legacy_scripts",
        "Option A": PROJECT_ROOT / "modernized" / "option_a_pandas",
        "Option B": PROJECT_ROOT / "modernized" / "option_b_airflow",
        "Option C": PROJECT_ROOT / "modernized" / "option_c_event_driven",
        "Shared": PROJECT_ROOT / "modernized" / "shared",
    }
    lines.append("| Component | Python Files | Lines of Code |")
    lines.append("|-----------|-------------|--------------|")
    for name, d in dirs.items():
        if d.exists():
            lines.append(f"| {name} | {_count_files(d)} | {_count_lines(d)} |")

    # --- Feature matrix ---
    lines.append("\n## 4. Feature Comparison\n")
    lines.append("| Feature | Legacy | Option A | Option B | Option C |")
    lines.append("|---------|--------|----------|----------|----------|")
    for feature, vals in FEATURE_MATRIX.items():
        lines.append(
            f"| {feature} | {vals['Legacy']} | {vals['Option A']} "
            f"| {vals['Option B']} | {vals['Option C']} |"
        )

    # --- Architecture diagrams ---
    lines.append("\n## 5. Architecture Overview\n")
    lines.append("### Option A: pandas + SQLAlchemy (Minimal Lift)\n")
    lines.append("```")
    lines.append("  daily_trades.csv ──> parse_trade_csv()")
    lines.append("                            │")
    lines.append("                       validate_trades()")
    lines.append("                            │")
    lines.append("                    calculate_amounts()  [vectorized]")
    lines.append("                            │")
    lines.append("  confirms.dat ────> parse_counterparty_dat()")
    lines.append("                            │")
    lines.append("                       reconcile()  [hash-join]")
    lines.append("                          /    \\")
    lines.append("                   to_csv()    to_db()  [SQLAlchemy]")
    lines.append("```\n")

    lines.append("### Option B: Airflow DAG\n")
    lines.append("```")
    lines.append("  ┌──────────────────────────────────────────────────┐")
    lines.append("  │  Airflow DAG: trade_processing_pipeline          │")
    lines.append("  │  Schedule: 30 6 * * 1-5                         │")
    lines.append("  │                                                  │")
    lines.append("  │  load_trades ─> validate ─> calculate_amounts   │")
    lines.append("  │                                    │             │")
    lines.append("  │              parse_confirms ───────┤             │")
    lines.append("  │                                    │             │")
    lines.append("  │                               reconcile          │")
    lines.append("  │                              /         \\         │")
    lines.append("  │                       write_db    write_csv      │")
    lines.append("  └──────────────────────────────────────────────────┘")
    lines.append("  Monitoring: Airflow UI  │  Retries: 2x @ 5 min")
    lines.append("```\n")

    lines.append("### Option C: Event-Driven (Watchdog)\n")
    lines.append("```")
    lines.append("                      ┌─────────────────┐")
    lines.append("  File system event ──│   TradeFileHandler  │")
    lines.append("  (daily_trades.csv)  │  (dedup by hash)   │")
    lines.append("                      └────────┬────────┘")
    lines.append("                               │")
    lines.append("                      ┌────────▼────────┐")
    lines.append("                      │  TradeProcessor  │")
    lines.append("                      │  State Machine:  │")
    lines.append("                      │  IDLE ─> WAITING │")
    lines.append("                      │  ─> PROCESSING   │")
    lines.append("                      │  ─> COMPLETE     │")
    lines.append("                      └────────┬────────┘")
    lines.append("                               │")
    lines.append("                      ┌────────▼────────┐")
    lines.append("                      │  Shared Pipeline │")
    lines.append("                      │  (parse/validate/│")
    lines.append("                      │   recon/output)  │")
    lines.append("                      └─────────────────┘")
    lines.append("  Cloud mapping:  S3 event → Lambda")
    lines.append("                  Blob trigger → Azure Function")
    lines.append("```\n")

    # --- Recommendation ---
    lines.append("## 6. Recommendation\n")
    lines.append(textwrap.dedent("""\
    | Criterion | Recommended Option |
    |-----------|-------------------|
    | Fastest migration | **Option A** — drop-in replacement, minimal infrastructure |
    | Best for growing team | **Option B** — Airflow provides scheduling, monitoring, and DAG versioning |
    | Most future-proof | **Option C** — event-driven maps cleanly to cloud-native (Lambda/Functions) |
    | Best for Meridian today | **Option A** — immediate value with minimal risk, then migrate to B or C |
    """))

    lines.append("### Migration Path\n")
    lines.append("```")
    lines.append("  Phase 1 (Week 1-2):  Deploy Option A as drop-in replacement")
    lines.append("                       ├── Replace hardcoded paths with env vars")
    lines.append("                       ├── Fix T+2 settlement bug")
    lines.append("                       └── Add structured logging")
    lines.append("")
    lines.append("  Phase 2 (Week 3-4):  Stand up Airflow or event infrastructure")
    lines.append("                       ├── Evaluate team's ops capacity")
    lines.append("                       └── Choose Option B (on-prem) or C (cloud)")
    lines.append("")
    lines.append("  Phase 3 (Week 5+):   Migrate remaining legacy scripts")
    lines.append("                       ├── calc_nav.py")
    lines.append("                       ├── reconciliation.py")
    lines.append("                       └── compliance_check.py")
    lines.append("```\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Trade modernization comparison")
    parser.add_argument("--date", default="20240315", help="Trade date YYYYMMDD")
    args = parser.parse_args()

    trade_date = args.date
    print(f"\n{'='*60}")
    print("  TRADE PROCESSING MODERNIZATION — COMPARISON HARNESS")
    print(f"  Date: {trade_date}")
    print(f"{'='*60}\n")

    results: List[Dict[str, Any]] = []

    # Run legacy
    print(">>> Running Legacy processor...")
    results.append(run_legacy(trade_date))

    # Run Option A
    print("\n>>> Running Option A (pandas + SQLAlchemy)...")
    results.append(run_option_a(trade_date))

    # Run Option B
    print("\n>>> Running Option B (Airflow tasks — standalone)...")
    results.append(run_option_b(trade_date))

    # Run Option C
    print("\n>>> Running Option C (Event-Driven)...")
    results.append(run_option_c(trade_date))

    # Generate report
    report = generate_report(results, trade_date)
    print("\n" + report)

    # Write to file
    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "modernization_comparison.md"
    with open(report_file, "w") as f:
        f.write(report)
    print(f"\nReport saved to: {report_file}")


if __name__ == "__main__":
    main()
