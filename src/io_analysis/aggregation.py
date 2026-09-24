"""Phase 5: collapse every traced neuron into a coarse "layer" label (input
category, processing role, output category, or "unknown"), then aggregate
the edge table by (source_layer, target_layer). See pathways.py for
individual-neuron drill-down. The four aggregation metrics are kept as
separate columns, not combined into one score.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from io_analysis.classification import build_classification
from io_analysis.load_data import PROJECT_ROOT, load_edges, load_nodes

LAYER_GRAPH_PATH = PROJECT_ROOT / "data" / "io_layer_graph.csv"

# io_role -> coarse processing layer name, per Phase 5's stated processing
# categories (optic_lobe, central_brain, ascending, descending, vnc).
PROCESSING_LAYER_BY_ROLE = {
    "optic_processing": "optic_lobe",
    "central_processing": "central_brain",
    "vnc_processing": "vnc",
    "ascending": "ascending",
    "descending": "descending",
}
OUTPUT_ROLES = {"motor_output", "endocrine_output", "other_efferent"}


def add_layer(classification: pl.DataFrame) -> pl.DataFrame:
    """Add a `layer` column (input_category / processing role / output_category /
    "unknown"). Unknown nodes keep a row rather than being dropped, so they
    don't silently disappear (~21% of the connectome) from the aggregated graph.
    """
    processing_branch = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for role, layer_name in PROCESSING_LAYER_BY_ROLE.items():
        processing_branch = processing_branch.when(pl.col("io_role") == role).then(pl.lit(layer_name))
    processing_branch = processing_branch.otherwise(pl.lit("unknown"))

    layer = (
        pl.when(pl.col("io_role") == "sensory_input").then(pl.col("input_category"))
        .when(pl.col("io_role").is_in(list(OUTPUT_ROLES))).then(pl.col("output_category"))
        .when(pl.col("io_role").is_in(list(PROCESSING_LAYER_BY_ROLE.keys()))).then(processing_branch)
        .otherwise(pl.lit("unknown"))
        .alias("layer")
    )
    return classification.with_columns(layer)


def build_layer_graph(
    edges: pl.DataFrame | None = None,
    classification: pl.DataFrame | None = None,
) -> pl.DataFrame:
    if edges is None:
        edges = load_edges()
    if classification is None:
        classification = build_classification(load_nodes())

    layered = add_layer(classification).select("bodyid", "layer")

    joined = (
        edges.join(layered.rename({"bodyid": "source", "layer": "source_layer"}), on="source", how="left")
        .join(layered.rename({"bodyid": "target", "layer": "target_layer"}), on="target", how="left")
    )

    if joined.select(pl.col("source_layer").is_null().any()).item() or joined.select(
        pl.col("target_layer").is_null().any()
    ).item():
        raise ValueError("Some edge endpoints did not match a classified node - classification/edges out of sync.")

    layer_graph = joined.group_by(["source_layer", "target_layer"]).agg(
        total_weight=pl.col("weight").sum(),
        n_unique_source_neurons=pl.col("source").n_unique(),
        n_unique_target_neurons=pl.col("target").n_unique(),
        n_directed_connections=pl.len(),
    ).sort(["source_layer", "target_layer"])

    return layer_graph


def save_layer_graph(layer_graph: pl.DataFrame, path: Path = LAYER_GRAPH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    layer_graph.write_csv(path)


def main() -> None:
    layer_graph = build_layer_graph()
    save_layer_graph(layer_graph)

    n_layers = len(
        set(layer_graph["source_layer"].to_list()) | set(layer_graph["target_layer"].to_list())
    )
    print(f"Layer graph: {layer_graph.height} (source_layer, target_layer) pairs across {n_layers} layers")
    print(f"Saved -> {LAYER_GRAPH_PATH}")

    print("\nTop 15 layer pairs by total_weight:")
    print(layer_graph.sort("total_weight", descending=True).head(15))

    print("\nTop 15 layer pairs by n_directed_connections:")
    print(layer_graph.sort("n_directed_connections", descending=True).head(15))


if __name__ == "__main__":
    main()
