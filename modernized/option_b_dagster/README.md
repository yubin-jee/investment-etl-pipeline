# Option B: Dagster Trade Processing Pipeline

Asset-based data pipeline with built-in lineage tracking, native date
partitioning, and a full observability UI.

## Architecture

Dagster models each processing stage as a **software-defined asset**.
The dependency graph is inferred automatically from function signatures:

```
raw_trades ──> validated_trades ──> enriched_trades ──┐
                                                      ├──> reconciled_trades
counterparty_confirms ────────────────────────────────┘
```

Each asset logs metadata (row counts, error counts) that is visible in the
Dagster UI, and every materialization is recorded for full lineage and
auditability.

## Installation

```bash
pip install -r modernized/requirements_option_b.txt
```

## Running

Launch the Dagster development server:

```bash
dagster dev -m modernized.option_b_dagster.definitions
```

Then open http://localhost:3000 in your browser.

### Materializing Assets

1. Navigate to the **Assets** page in the Dagster UI.
2. Select the assets you want to materialize (or click **Materialize all**).
3. Choose a partition (date) to process — e.g., `2024-03-15`.
4. Click **Materialize** and monitor the run in the **Runs** tab.

For backfills across a date range, select multiple partitions and Dagster
will schedule one run per partition with automatic retries
(max 3 retries, 60-second delay).

## Configuration

The pipeline reads file paths from `config/batch_config.ini` via
`TradeFileResource`. You can override the defaults by editing the
resource config in `definitions.py`:

```python
TradeFileResource(
    base_data_dir="path/to/data",
    config_path="path/to/batch_config.ini",
)
```

## Pros

- **Full observability UI** — built-in web dashboard with run history,
  asset lineage graph, and metadata visualization.
- **Asset lineage graph** — automatic dependency tracking between pipeline
  stages; no manual DAG wiring.
- **Built-in retries** — configurable retry policies with backoff per asset.
- **Native date partitioning** — first-class support for daily partitions
  with one-click backfill across date ranges.
- **Testing utilities** — Dagster provides `build_asset_context` and
  `materialize_to_memory` for unit and integration testing.

## Cons

- **Requires Dagster webserver infrastructure** — needs a running
  webserver/daemon process (or Dagster Cloud) for production use.
- **Moderate learning curve** — asset-based paradigm and resource injection
  differ from traditional scripting.
- **Newer ecosystem** — smaller community compared to Airflow; fewer
  third-party integrations.
