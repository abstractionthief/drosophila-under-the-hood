"""Phase 6: input_category x output_category connectivity matrix, built on
the full 165k-node/25.5M-edge Traced graph as scipy.sparse (networkx can't
hold this at interactive speed). All metrics are topological graph measures,
not biological signal-strength claims - see weighted_shortest_path (cost =
1/weight) and max_flow (capacity = weight) below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra, maximum_flow

from io_analysis.classification import build_classification
from io_analysis.load_data import PROJECT_ROOT, load_edges, load_nodes

MATRIX_PATH = PROJECT_ROOT / "data" / "io_matrix.csv"

INPUT_CATEGORIES = [
    "vision", "olfaction", "gustation", "mechanosensation",
    "proprioception", "hygrosensation", "thermosensation", "other_sensory",
]
OUTPUT_CATEGORIES = [
    "front_leg", "middle_leg", "hind_leg", "wing", "haltere",
    "neck", "proboscis", "abdomen", "endocrine", "other_motor",
]
DEFAULT_MAX_HOPS = 3
# Stable name independent of max_hops - a prior f"n_pairs_within_{max_hops}_hops"
# got hardcoded downstream (export_app_data.py, app.js, index.html), so changing
# max_hops silently broke consumers. Now only the manifest's max_hops field changes.
N_PAIRS_WITHIN_HOPS_COLUMN = "n_pairs_within_hops"


@dataclass
class NeuronGraph:
    n: int
    adjacency: sp.csr_matrix       # weight = synapse count
    cost: sp.csr_matrix            # weight = 1 / synapse count (for weighted shortest path)
    reverse_adjacency: sp.csr_matrix
    idx_to_bodyid: np.ndarray
    input_category: np.ndarray     # length n, aligned to adjacency row/col order
    output_category: np.ndarray


def build_graph() -> NeuronGraph:
    nodes = load_nodes()
    classification = build_classification(nodes)
    traced_ids = nodes.filter(pl.col("status") == "Traced")["bodyid"].to_numpy().astype(np.int64)
    n = len(traced_ids)

    # Fix node order once so array index i always means bodyid traced_ids[i].
    ordered = pl.DataFrame({"bodyid": traced_ids, "idx": np.arange(n)}).join(
        classification.with_columns(pl.col("bodyid").cast(pl.Int64)), on="bodyid", how="left"
    ).sort("idx")
    input_category = ordered["input_category"].to_numpy()
    output_category = ordered["output_category"].to_numpy()

    idx_map = {int(b): i for i, b in enumerate(traced_ids)}
    edges = load_edges()

    # Check membership explicitly - a stale edges parquet vs. census would
    # otherwise surface as a bare KeyError in the list comprehension below.
    edge_ids = set(edges["source"].unique().to_list()) | set(edges["target"].unique().to_list())
    missing = edge_ids - set(idx_map)
    if missing:
        sample = sorted(missing)[:5]
        raise ValueError(
            f"{len(missing)} edge endpoint id(s) are not Traced in the current census "
            f"(stale data/raw/io_edges.parquet vs. data/io_census_nodes.csv?), e.g. {sample}"
        )

    src_i = np.array([idx_map[int(x)] for x in edges["source"].to_numpy()])
    tgt_i = np.array([idx_map[int(x)] for x in edges["target"].to_numpy()])
    weights = edges["weight"].to_numpy().astype(np.int32)

    adjacency = sp.csr_matrix((weights, (src_i, tgt_i)), shape=(n, n))
    cost = sp.csr_matrix((1.0 / weights, (src_i, tgt_i)), shape=(n, n))
    reverse_adjacency = adjacency.transpose().tocsr()

    return NeuronGraph(
        n=n, adjacency=adjacency, cost=cost, reverse_adjacency=reverse_adjacency,
        idx_to_bodyid=traced_ids, input_category=input_category, output_category=output_category,
    )


def category_indices(category_arr: np.ndarray, value: str) -> np.ndarray:
    return np.where(category_arr == value)[0]


def compute_pooled_metrics(graph: NeuronGraph) -> pl.DataFrame:
    """reachable / shortest_path_hops / weighted_shortest_path per category pair.
    "Pooled": all neurons of an input_category act as one combined source
    set (min_only=True Dijkstra), not per-neuron-pair distances.
    """
    rows = []
    for in_cat in INPUT_CATEGORIES:
        src_idx = category_indices(graph.input_category, in_cat)
        if len(src_idx) == 0:
            continue
        hop_dist = dijkstra(graph.adjacency, directed=True, indices=src_idx, unweighted=True, min_only=True)
        w_dist = dijkstra(graph.cost, directed=True, indices=src_idx, unweighted=False, min_only=True)

        for out_cat in OUTPUT_CATEGORIES:
            tgt_idx = category_indices(graph.output_category, out_cat)
            if len(tgt_idx) == 0:
                rows.append(dict(input_category=in_cat, output_category=out_cat,
                                  reachable=False, shortest_path_hops=None, weighted_shortest_path=None))
                continue
            hops = hop_dist[tgt_idx]
            finite_hops = hops[np.isfinite(hops)]
            reachable = finite_hops.size > 0
            wdist = w_dist[tgt_idx]
            finite_w = wdist[np.isfinite(wdist)]
            rows.append(dict(
                input_category=in_cat,
                output_category=out_cat,
                reachable=bool(reachable),
                shortest_path_hops=float(finite_hops.min()) if reachable else None,
                weighted_shortest_path=float(finite_w.min()) if finite_w.size > 0 else None,
            ))
    return pl.DataFrame(rows)


def compute_pairwise_hop_counts(graph: NeuronGraph, max_hops: int = DEFAULT_MAX_HOPS) -> dict[tuple[str, str], int]:
    """Exact count of (input_neuron, output_neuron) pairs within max_hops.
    One hop-limited reverse BFS per output-category neuron - true
    per-neuron-pair counts, unlike the pooled metrics above.
    """
    counts: dict[tuple[str, str], int] = {(i, o): 0 for i in INPUT_CATEGORIES for o in OUTPUT_CATEGORIES}
    for out_cat in OUTPUT_CATEGORIES:
        out_idx = category_indices(graph.output_category, out_cat)
        for o in out_idx:
            dist = dijkstra(
                graph.reverse_adjacency, directed=True, indices=[o],
                unweighted=True, limit=max_hops, min_only=True,
            )
            reached = np.isfinite(dist)
            reached_cats = graph.input_category[reached]
            vals, cnts = np.unique(reached_cats, return_counts=True)
            for v, c in zip(vals, cnts):
                if v in INPUT_CATEGORIES:
                    counts[(v, out_cat)] += int(c)
    return counts


def compute_max_flow(graph: NeuronGraph) -> dict[tuple[str, str], int]:
    """Max-flow between a virtual super-source/sink per category pair.
    Capacity = synapse weight.
    """
    n = graph.n
    A = graph.adjacency.tocoo()
    base_rows, base_cols, base_w = A.row, A.col, A.data

    flows: dict[tuple[str, str], int] = {}
    for in_cat in INPUT_CATEGORIES:
        src_idx = category_indices(graph.input_category, in_cat)
        if len(src_idx) == 0:
            continue
        for out_cat in OUTPUT_CATEGORIES:
            tgt_idx = category_indices(graph.output_category, out_cat)
            if len(tgt_idx) == 0:
                flows[(in_cat, out_cat)] = 0
                continue
            SS, ST = n, n + 1
            big_cap = np.int32(2_000_000_000 // max(len(src_idx), len(tgt_idx), 1))
            extra_rows = np.concatenate([np.full(len(src_idx), SS), tgt_idx])
            extra_cols = np.concatenate([src_idx, np.full(len(tgt_idx), ST)])
            extra_w = np.concatenate([
                np.full(len(src_idx), big_cap, dtype=np.int32),
                np.full(len(tgt_idx), big_cap, dtype=np.int32),
            ])
            rows = np.concatenate([base_rows, extra_rows])
            cols = np.concatenate([base_cols, extra_cols])
            w = np.concatenate([base_w, extra_w])
            augmented = sp.csr_matrix((w, (rows, cols)), shape=(n + 2, n + 2))
            result = maximum_flow(augmented, SS, ST)
            flows[(in_cat, out_cat)] = int(result.flow_value)
    return flows


def compute_category_synaptic_totals(graph: NeuronGraph) -> tuple[dict[str, int], dict[str, int]]:
    """Total presynaptic (outgoing) weight per input_category, and total
    postsynaptic (incoming) weight per output_category - the denominators
    for normalizing max_flow. Raw max_flow/total_weight heavily favor large
    categories (e.g. vision, 6,091 neurons, vs. thermosensation, 25) -
    dividing by a category's total weights rescales graph capacity for
    comparison. This is not an observed fraction of biological input/output;
    independently computed pairwise flows can reuse the same capacities.
    """
    row_sums = np.asarray(graph.adjacency.sum(axis=1)).ravel()
    col_sums = np.asarray(graph.adjacency.sum(axis=0)).ravel()
    presynaptic_total = {
        cat: int(row_sums[category_indices(graph.input_category, cat)].sum()) for cat in INPUT_CATEGORIES
    }
    postsynaptic_total = {
        cat: int(col_sums[category_indices(graph.output_category, cat)].sum()) for cat in OUTPUT_CATEGORIES
    }
    return presynaptic_total, postsynaptic_total


def build_io_matrix(max_hops: int = DEFAULT_MAX_HOPS, compute_flow: bool = True) -> pl.DataFrame:
    graph = build_graph()
    matrix = compute_pooled_metrics(graph)

    hop_counts = compute_pairwise_hop_counts(graph, max_hops=max_hops)
    matrix = matrix.with_columns(
        pl.struct(["input_category", "output_category"])
        .map_elements(lambda s: hop_counts.get((s["input_category"], s["output_category"]), 0), return_dtype=pl.Int64)
        .alias(N_PAIRS_WITHIN_HOPS_COLUMN)
    )

    if compute_flow:
        flows = compute_max_flow(graph)
        matrix = matrix.with_columns(
            pl.struct(["input_category", "output_category"])
            .map_elements(lambda s: flows.get((s["input_category"], s["output_category"]), 0), return_dtype=pl.Int64)
            .alias("max_flow")
        )
        presynaptic_total, postsynaptic_total = compute_category_synaptic_totals(graph)
        # A disconnected/absent category has no capacity to normalize by.
        # Null means undefined; 0/0 would become NaN and invalid browser JSON.
        input_total = pl.col("input_category").replace_strict(presynaptic_total, default=None)
        output_total = pl.col("output_category").replace_strict(postsynaptic_total, default=None)
        matrix = matrix.with_columns(
            (pl.col("max_flow") / pl.when(input_total > 0).then(input_total).otherwise(None))
            .alias("max_flow_frac_of_input_output"),
            (pl.col("max_flow") / pl.when(output_total > 0).then(output_total).otherwise(None))
            .alias("max_flow_frac_of_output_input"),
        )

    return matrix


def save_matrix(matrix: pl.DataFrame, path: Path = MATRIX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    matrix.write_csv(path)


def main() -> None:
    import time
    t0 = time.time()
    matrix = build_io_matrix()
    save_matrix(matrix)
    print(f"Built {matrix.height}-row input x output matrix in {time.time()-t0:.1f}s -> {MATRIX_PATH}")
    with pl.Config(tbl_rows=100, tbl_cols=-1):
        print(matrix.sort(["input_category", "output_category"]))


if __name__ == "__main__":
    main()
