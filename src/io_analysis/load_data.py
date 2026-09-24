"""Load and lightly validate the raw MaleCNS I/O datasets (node census, edge
table, edge manifest) produced by the R extraction scripts. No classification
or aggregation here - see classification.py / aggregation.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NODES_PATH = PROJECT_ROOT / "data" / "io_census_nodes.csv"
EDGES_PATH = PROJECT_ROOT / "data" / "raw" / "io_edges.parquet"
EDGES_MANIFEST_PATH = PROJECT_ROOT / "data" / "raw" / "io_edges_manifest.json"

REQUIRED_NODE_COLUMNS = {"bodyid", "status", "superclass", "class", "subclass", "exitNerve"}
REQUIRED_EDGE_COLUMNS = {"source", "target", "weight"}
MAX_BODY_ID = 2**63 - 1
MAX_EDGE_WEIGHT = 2**31 - 1  # graph.py/scipy maximum_flow use signed int32 capacities


def _validate_integer_column(values: pl.Series, table: str, maximum: int) -> None:
    """Check raw values before casting, which would silently truncate floats.

    Integer-valued floats are expected from R. Compare scalar extrema with
    Python integers so the int64 upper bound isn't rounded up to 2**63 when
    the source column is floating point.
    """
    column = values.name
    if values.is_null().any():
        raise ValueError(f"{table} has null {column} value(s).")
    if not (values.dtype.is_integer() or values.dtype.is_float()):
        raise ValueError(f"{table} column {column!r} must contain numeric integer values.")
    if values.dtype.is_float():
        if not values.is_finite().all():
            raise ValueError(f"{table} column {column!r} has non-finite value(s).")
        if (values != values.floor()).any():
            raise ValueError(f"{table} column {column!r} has fractional value(s).")
    if len(values) == 0:
        return
    if values.min() < 1:
        raise ValueError(f"{table} has non-positive {column} value(s) - values must be >=1.")
    if values.max() > maximum:
        raise ValueError(f"{table} column {column!r} exceeds its supported maximum {maximum}.")


def validate_nodes(nodes: pl.DataFrame) -> None:
    """Boundary checks a downstream classification/graph bug would otherwise
    surface as a confusing failure several modules away from the real cause.
    """
    missing_cols = REQUIRED_NODE_COLUMNS - set(nodes.columns)
    if missing_cols:
        raise ValueError(f"Node census is missing required column(s): {sorted(missing_cols)}")
    _validate_integer_column(nodes["bodyid"], "Node census", MAX_BODY_ID)
    n_dup = nodes.height - nodes["bodyid"].n_unique()
    if n_dup > 0:
        raise ValueError(f"Node census has {n_dup} duplicate bodyid(s) - expected one row per body.")


def validate_edges(edges: pl.DataFrame) -> None:
    missing_cols = REQUIRED_EDGE_COLUMNS - set(edges.columns)
    if missing_cols:
        raise ValueError(f"Edge table is missing required column(s): {sorted(missing_cols)}")
    _validate_integer_column(edges["source"], "Edge table", MAX_BODY_ID)
    _validate_integer_column(edges["target"], "Edge table", MAX_BODY_ID)
    _validate_integer_column(edges["weight"], "Edge table", MAX_EDGE_WEIGHT)
    # Duplicate (source, target) rows matter beyond row count: scipy.sparse
    # silently *sums* duplicate entries when building the adjacency matrix,
    # but a separately-built 1/weight cost matrix sums 1/w_1 + 1/w_2 + ... ,
    # not 1/(w_1+w_2) - the two matrices would then disagree about the same
    # edge's effective cost. Fail loudly instead of letting that diverge.
    n_dup = edges.height - edges.select(["source", "target"]).unique().height
    if n_dup > 0:
        raise ValueError(
            f"Edge table has {n_dup} duplicate (source, target) row(s) - "
            "aggregate to one row per pair (summing weight) before building adjacency/cost matrices."
        )


def load_nodes() -> pl.DataFrame:
    """Load the Phase 1 node census (data/io_census_nodes.csv), raw fields only."""
    if not NODES_PATH.exists():
        raise FileNotFoundError(f"{NODES_PATH} not found - run r/build_io_census.R first.")
    # R's write.csv() writes missing values as a bare, unquoted `NA` token.
    # polars' default null_values is [""] only, so without this the string
    # "NA" would silently survive as real data instead of becoming null.
    nodes = pl.read_csv(NODES_PATH, infer_schema_length=None, null_values=["NA"])
    validate_nodes(nodes)
    # Round bodyids get written as scientific notation (1e+05), forcing
    # polars to infer Float64 - cast once here at the R->Python boundary.
    return nodes.with_columns(pl.col("bodyid").cast(pl.Int64))


def load_edges() -> pl.DataFrame:
    """Load the Phase 3 edge table (data/raw/io_edges.parquet): source, target, weight."""
    if not EDGES_PATH.exists():
        raise FileNotFoundError(f"{EDGES_PATH} not found - run r/build_io_connectivity.R first.")
    # Same R->Python float64 boundary issue as load_nodes()'s bodyid.
    edges = pl.read_parquet(EDGES_PATH)
    validate_edges(edges)
    validate_edges_manifest(edges, load_edges_manifest())
    edges = edges.with_columns(
        pl.col("source").cast(pl.Int64),
        pl.col("target").cast(pl.Int64),
        pl.col("weight").cast(pl.Int64),
    )
    return edges


def load_edges_manifest() -> dict:
    """Load the provenance manifest written alongside the edge parquet file."""
    if not EDGES_MANIFEST_PATH.exists():
        raise FileNotFoundError(f"{EDGES_MANIFEST_PATH} not found - run r/build_io_connectivity.R first.")
    return json.loads(EDGES_MANIFEST_PATH.read_text())


def validate_edges_against_nodes(nodes: pl.DataFrame, edges: pl.DataFrame) -> None:
    """Raise if any edge endpoint is missing from the node census.

    Mirrors the validation r/build_io_connectivity.R already performed at
    extraction time; re-checked here since this is the boundary where R
    output becomes Python input.
    """
    node_ids = set(nodes["bodyid"].to_list())
    edge_ids = set(edges["source"].unique().to_list()) | set(edges["target"].unique().to_list())
    missing = edge_ids - node_ids
    if missing:
        sample = sorted(missing)[:5]
        raise ValueError(f"{len(missing)} edge endpoint id(s) missing from node census, e.g. {sample}")


EXPECTED_DATASET = "male-cns:v1.0"


def validate_edges_manifest(edges: pl.DataFrame, manifest: dict) -> None:
    """Catch a stale/mismatched manifest before it silently mislabels every
    downstream export as `male-cns:v1.0` regardless of what was actually
    fetched, and catch a parquet that doesn't match its own manifest's
    row count (a partial/interrupted extraction re-run, for example).
    """
    if not isinstance(manifest, dict):
        raise ValueError("Edges manifest must be a JSON object.")
    dataset = manifest.get("dataset")
    if dataset != EXPECTED_DATASET:
        raise ValueError(f"Edges manifest declares dataset {dataset!r}, expected {EXPECTED_DATASET!r}.")
    manifest_rows = manifest.get("row_count")
    if isinstance(manifest_rows, bool) or not isinstance(manifest_rows, int) or manifest_rows < 0:
        raise ValueError("Edges manifest must declare a non-negative integer row_count.")
    if manifest_rows != edges.height:
        raise ValueError(
            f"Edges manifest declares row_count={manifest_rows}, but the parquet file has "
            f"{edges.height} rows - manifest and data have gone out of sync."
        )


def main() -> None:
    nodes = load_nodes()
    edges = load_edges()
    manifest = load_edges_manifest()

    validate_edges_against_nodes(nodes, edges)
    validate_edges_manifest(edges, manifest)

    print(f"Nodes: {nodes.height} rows, {nodes.width} cols")
    print(f"Edges: {edges.height} rows, {edges.width} cols")
    print(f"Edges manifest dataset: {manifest['dataset']}, extracted {manifest['extraction_timestamp_utc']}")
    print("Validation: all edge endpoints present in node census.")

    traced = nodes.filter(pl.col("status") == "Traced")
    print(f"Traced nodes: {traced.height}")

    weight_stats = edges.select(
        pl.col("weight").min().alias("min"),
        pl.col("weight").median().alias("median"),
        pl.col("weight").mean().alias("mean"),
        pl.col("weight").max().alias("max"),
    )
    print("Edge weight stats (recomputed in Python, cross-check vs R manifest):")
    print(weight_stats)


if __name__ == "__main__":
    main()
