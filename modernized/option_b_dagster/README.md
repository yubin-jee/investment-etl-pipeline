# Option B: Dagster Asset-Based Trade Processor

## How It Works

This module implements the trade processing pipeline using **Dagster's asset-based
materialization** model. Each stage of the ETL pipeline is defined as a Dagster
`@asset`, forming a dependency graph (lineage) that Dagster tracks automatically:

```
raw_trades ──► validated_trades ──► enriched_trades ──► reconciled_trades
                                                    ▲
                               counterparty_confirms ┘
```

Assets are materialized on demand (or on a schedule) and Dagster records metadata
for every run — row counts, error counts, and reconciliation statistics are
visible directly in the Dagster UI.

## Installation

```bash
pip install -r modernized/requirements_option_b.txt
```

## Launching the Dagster UI

```bash
dagster dev -m modernized.option_b_dagster.definitions
```

Then open http://localhost:3000 in your browser.

## Materializing Assets

1. Navigate to the **Assets** page in the Dagster UI.
2. Select the assets you want to materialize (or click **Materialize all**).
3. For partitioned assets (e.g. `raw_trades`), choose the partition date
   corresponding to the trade file you want to process (e.g. `2024-01-15`).
4. Monitor the run in the **Runs** tab — each asset logs metadata such as
   row counts and reconciliation statistics.

## Project Structure

| File             | Purpose                                             |
|------------------|-----------------------------------------------------|
| `resources.py`   | `TradeFileResource` — file paths and configuration  |
| `assets.py`      | `@asset` definitions for each pipeline stage        |
| `definitions.py` | `Definitions` object combining assets and resources |

## Pros

- **Full UI with lineage** — visual DAG of asset dependencies, run history,
  and metadata tracking out of the box.
- **Native partitions** — `DailyPartitionsDefinition` lets you process any
  historical date without changing code.
- **Retry policies** — built-in `RetryPolicy(max_retries=3, delay=60)` for
  transient failures.
- **Metadata tracking** — row counts, error counts, and reconciliation stats
  are recorded per materialization and visible in the UI.
- **Incremental adoption** — assets can be materialized independently; you
  don't have to run the full pipeline every time.

## Cons

- **Learning curve** — Dagster's asset/resource/IO manager model takes time
  to learn compared to a plain script.
- **Additional infrastructure** — requires the Dagster webserver (and
  optionally a daemon for schedules/sensors) to be running.
- **Heavier dependency footprint** — pulls in gRPC, SQLAlchemy, and other
  transitive dependencies.
