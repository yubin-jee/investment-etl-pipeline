# Option B: Dagster Asset-Based Trade Processing Pipeline

## Overview

This option wraps the shared common layer (`modernized/common/`) with
[Dagster](https://dagster.io/)'s **asset-based** orchestration paradigm.

Instead of defining a DAG of tasks, Dagster models the pipeline as a graph of
**software-defined assets** — each asset is a materialized dataset that declares
its upstream dependencies. Dagster automatically infers the execution order,
tracks lineage, and provides a rich web UI for observability.

### Asset Graph

```
raw_trades ──► validated_trades ──► enriched_trades ──┐
                                                      ├──► reconciled_trades
counterparty_confirms ────────────────────────────────┘
```

| Asset | Description |
|---|---|
| `raw_trades` | Loads the daily trade CSV via `common.parsers.load_trades_csv` |
| `validated_trades` | Validates & deduplicates via `common.validation.validate_trades` |
| `enriched_trades` | Calculates gross/net amounts, fixes settlement dates via T+2 |
| `counterparty_confirms` | Loads fixed-width broker confirmations via `common.parsers.load_counterparty_file` |
| `reconciled_trades` | Merges trades with confirms and determines match status |

## Installation

```bash
pip install -r modernized/requirements_option_b.txt
```

## Running the Dagster Webserver

```bash
dagster dev -m modernized.option_b_dagster.definitions
```

Then open [http://localhost:3000](http://localhost:3000) in your browser to
access the Dagster UI.

## Materializing Assets

### Via the UI

1. Open the Dagster UI at `http://localhost:3000`.
2. Navigate to the **Assets** page.
3. Select the assets you want to materialize (or click **Materialize all**).
4. Click **Materialize** to trigger a run.

### Via the CLI

```bash
dagster asset materialize --select raw_trades,validated_trades,enriched_trades,counterparty_confirms,reconciled_trades \
    -m modernized.option_b_dagster.definitions
```

## Configuration

The `TradeFileResource` is configured with default paths and a `run_date`.
Override these values in the Dagster UI launchpad or by editing
`definitions.py`:

```python
resources={
    "trade_files": TradeFileResource(
        base_dir="legacy_data/trades",
        report_dir="reports",
        run_date="20240315",
    ),
}
```

## Pros

- **Full UI with lineage** — asset graph visualization, run history, and metadata tracking out of the box
- **Built-in retry** — configurable retry policies per asset with backoff
- **Asset-level materialization** — re-run individual assets without re-processing the entire pipeline
- **Native partitioning support** — easily partition by date or other dimensions
- **Excellent observability** — structured logging, metadata, and alerting via Dagster's event system
- **Testing utilities** — first-class support for unit testing assets with `build_asset_context`

## Cons

- **Requires Dagster infrastructure** — needs the Dagster webserver (dagster-webserver) and daemon for scheduling
- **Moderate learning curve** — the asset-based mental model differs from traditional task-based DAGs
- **Smaller community than Airflow** — fewer third-party integrations and community resources compared to Apache Airflow
