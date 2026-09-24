"""Phase 7: pathway drill-down for one (input_category, output_category) pair
- a reduced subgraph, never the whole connectome. A node is "relevant" if
forward_hops + backward_hops <= max_hops (lies on an actual short path, not
just near either end). Outputs nodes/edges/paths tables under data/pathways/.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

from io_analysis.graph import NeuronGraph, build_graph, category_indices
from io_analysis.load_data import PROJECT_ROOT, load_nodes

PATHWAYS_DIR = PROJECT_ROOT / "data" / "pathways"

ROLE_GROUP_BY_IO_ROLE = {
    "sensory_input": "sensory_input",
    "central_processing": "central_processing",
    "optic_processing": "central_processing",  # folded in: not one of Phase 7's 5 named groups
    "descending": "descending",
    "vnc_processing": "vnc",
    "motor_output": "motor",
}
# Anything else (ascending, endocrine_output, other_efferent, unknown) -> "other"


class EmptyCategoryError(ValueError):
    """An (input_category, output_category) pair has no members on one side.
    A dedicated subclass so sweeping callers can skip this without catching
    (and silently swallowing) a bare ValueError."""


def _weight_filtered(graph: NeuronGraph, minimum_weight: int) -> sp.csr_matrix:
    if minimum_weight <= 1:
        return graph.adjacency
    A = graph.adjacency.tocoo()
    keep = A.data >= minimum_weight
    return sp.csr_matrix((A.data[keep], (A.row[keep], A.col[keep])), shape=graph.adjacency.shape)


def _reconstruct_shortest_path(
    filtered: sp.csr_matrix, source_idx: np.ndarray, target_idx: np.ndarray, max_hops: int
) -> list[int]:
    """One actual forward-shortest source->target node path (indices), or []
    if none exists within max_hops. Used to force-preserve a complete route
    before select_relevant_nodes()'s max_nodes cap can fragment it.
    """
    dist, pred, _sources = dijkstra(
        filtered, directed=True, indices=source_idx, unweighted=True,
        limit=max_hops, min_only=True, return_predecessors=True,
    )
    reachable_targets = target_idx[np.isfinite(dist[target_idx])]
    if len(reachable_targets) == 0:
        return []
    best_target = int(reachable_targets[np.argmin(dist[reachable_targets])])
    path = [best_target]
    cur = best_target
    while pred[cur] >= 0:
        cur = int(pred[cur])
        path.append(cur)
    path.reverse()
    return path


def select_relevant_nodes(
    graph: NeuronGraph,
    input_category: str,
    output_category: str,
    max_hops: int,
    minimum_weight: int,
    max_nodes: int,
) -> np.ndarray:
    filtered = _weight_filtered(graph, minimum_weight)
    source_idx = category_indices(graph.input_category, input_category)
    target_idx = category_indices(graph.output_category, output_category)
    if len(source_idx) == 0:
        raise EmptyCategoryError(f"No neurons found for input_category={input_category!r}")
    if len(target_idx) == 0:
        raise EmptyCategoryError(f"No neurons found for output_category={output_category!r}")

    fwd = dijkstra(filtered, directed=True, indices=source_idx, unweighted=True, limit=max_hops, min_only=True)
    bwd = dijkstra(filtered.transpose().tocsr(), directed=True, indices=target_idx,
                    unweighted=True, limit=max_hops, min_only=True)

    total_hops = fwd + bwd
    relevant = np.where(np.isfinite(total_hops) & (total_hops <= max_hops))[0]

    if len(relevant) > max_nodes:
        # A pure "closest by total_hops" truncation can fragment every complete
        # route (ties get picked in index order, not by which path they belong
        # to), leaving 0 paths even when the whole-graph matrix reports this
        # pair as reachable. Force-preserve one real path first, then fill the
        # rest of the budget by the existing closeness ranking.
        forced_path = _reconstruct_shortest_path(filtered, source_idx, target_idx, max_hops)
        forced = np.array(forced_path, dtype=relevant.dtype)
        remaining_budget = max_nodes - len(forced)
        rest = np.setdiff1d(relevant, forced, assume_unique=False)
        if remaining_budget > 0 and len(rest) > 0:
            order = np.argsort(total_hops[rest])
            rest = rest[order[:remaining_budget]]
        else:
            rest = rest[:0]
        relevant = np.union1d(forced, rest)

    return relevant


def build_induced_edges(graph: NeuronGraph, minimum_weight: int, relevant_idx: np.ndarray) -> pl.DataFrame:
    filtered = _weight_filtered(graph, minimum_weight).tocoo()
    # Vectorized boolean membership, not a per-edge Python `in` check - at
    # ~25.5M unfiltered edges the latter cost billions of ops across the 80-pair loop.
    is_relevant = np.zeros(graph.n, dtype=bool)
    is_relevant[relevant_idx] = True
    mask = is_relevant[filtered.row] & is_relevant[filtered.col]
    rows = filtered.row[mask]
    cols = filtered.col[mask]
    w = filtered.data[mask]
    return pl.DataFrame({
        "source": graph.idx_to_bodyid[rows],
        "target": graph.idx_to_bodyid[cols],
        "weight": w,
    })


def build_node_table(graph: NeuronGraph, nodes_meta: pl.DataFrame, relevant_idx: np.ndarray) -> pl.DataFrame:
    bodyids = graph.idx_to_bodyid[relevant_idx]
    # Extended past Phase 7's minimum field list to also serve Neuron Detail (View 4).
    meta_cols = [
        "bodyid", "type", "name", "superclass", "class", "subclass",
        "somaSide", "somaNeuromere", "consensusNt", "predictedNt", "receptorType",
        "entryNerve", "exitNerve", "flywireType", "mancType", "hemibrainType",
    ]
    return pl.DataFrame({"bodyid": bodyids}).join(nodes_meta.select(meta_cols), on="bodyid", how="left")


def find_top_paths(
    graph: NeuronGraph,
    edges_df: pl.DataFrame,
    input_category: str,
    output_category: str,
    relevant_idx: np.ndarray,
    max_hops: int,
    top_n_paths: int,
) -> pl.DataFrame:
    """Enumerate simple paths on the small induced (already max_nodes-capped)
    subgraph via one virtual super-source/super-sink search, then rank by
    bottleneck (min edge) weight. NOT a global top-N guarantee: enumeration
    stops after the first 50,000 DFS-discovered paths and only then sorts -
    a traversal-order-dependent sample of an already-reduced subgraph, not
    an exhaustive search over the whole connectome.
    """
    G = nx.DiGraph()
    for row in edges_df.iter_rows(named=True):
        G.add_edge(row["source"], row["target"], weight=row["weight"])

    relevant_set = set(graph.idx_to_bodyid[relevant_idx].tolist())
    source_bodyids = [
        b for b in graph.idx_to_bodyid[category_indices(graph.input_category, input_category)]
        if b in relevant_set and b in G
    ]
    target_bodyids = [
        b for b in graph.idx_to_bodyid[category_indices(graph.output_category, output_category)]
        if b in relevant_set and b in G
    ]
    if not source_bodyids or not target_bodyids:
        return pl.DataFrame(schema={"path": pl.Utf8, "hops": pl.Int64, "total_weight": pl.Int64, "bottleneck_weight": pl.Int64})

    SUPER_SOURCE, SUPER_SINK = "__SOURCE__", "__SINK__"
    for b in source_bodyids:
        G.add_edge(SUPER_SOURCE, b, weight=0)
    for b in target_bodyids:
        G.add_edge(b, SUPER_SINK, weight=0)

    paths = []
    try:
        for path in nx.all_simple_paths(G, SUPER_SOURCE, SUPER_SINK, cutoff=max_hops + 2):
            real_path = path[1:-1]  # drop virtual endpoints
            if len(real_path) < 2:
                continue
            weights = [G[real_path[i]][real_path[i + 1]]["weight"] for i in range(len(real_path) - 1)]
            paths.append({
                "path": "->".join(str(b) for b in real_path),
                "hops": len(real_path) - 1,
                "total_weight": int(sum(weights)),
                "bottleneck_weight": int(min(weights)),
            })
            if len(paths) >= 50_000:  # hard safety cap on enumeration itself
                break
    except nx.NetworkXNoPath:
        pass

    if not paths:
        return pl.DataFrame(schema={"path": pl.Utf8, "hops": pl.Int64, "total_weight": pl.Int64, "bottleneck_weight": pl.Int64})

    return (
        pl.DataFrame(paths)
        .sort("bottleneck_weight", descending=True)
        .head(top_n_paths)
    )


def load_graph_context() -> tuple[NeuronGraph, pl.DataFrame]:
    """Build the neuron graph and node metadata (with io_role) once, for reuse
    across many build_pathway_drilldown() calls (e.g. precomputing all
    category pairs for the Phase 8 app)."""
    from io_analysis.classification import build_classification

    graph = build_graph()
    nodes_meta_raw = load_nodes()
    classification = build_classification(nodes_meta_raw)
    nodes_meta = nodes_meta_raw.join(classification.select("bodyid", "io_role"), on="bodyid", how="left")
    return graph, nodes_meta


def build_pathway_drilldown(
    input_category: str,
    output_category: str,
    max_hops: int = 3,
    minimum_weight: int = 1,
    top_n_paths: int = 20,
    max_nodes: int = 150,
    graph: NeuronGraph | None = None,
    nodes_meta: pl.DataFrame | None = None,
) -> dict[str, pl.DataFrame]:
    """Build one pathway drill-down. Pass `graph`/`nodes_meta` (see
    load_graph_context()) when calling this in a loop over many category
    pairs - rebuilding them per call is the dominant cost otherwise.
    """
    if graph is None or nodes_meta is None:
        graph, nodes_meta = load_graph_context()

    relevant_idx = select_relevant_nodes(graph, input_category, output_category, max_hops, minimum_weight, max_nodes)
    edges_df = build_induced_edges(graph, minimum_weight, relevant_idx)
    nodes_df = build_node_table(graph, nodes_meta, relevant_idx)

    role_map = nodes_meta.select("bodyid", "io_role")
    nodes_df = nodes_df.join(role_map, on="bodyid", how="left").with_columns(
        pl.col("io_role").map_elements(lambda r: ROLE_GROUP_BY_IO_ROLE.get(r, "other"), return_dtype=pl.Utf8)
        .alias("role_group")
    ).drop("io_role")

    paths_df = find_top_paths(graph, edges_df, input_category, output_category, relevant_idx, max_hops, top_n_paths)

    return {"nodes": nodes_df, "edges": edges_df, "paths": paths_df}


def save_pathway_drilldown(input_category: str, output_category: str, tables: dict[str, pl.DataFrame]) -> Path:
    out_dir = PATHWAYS_DIR / f"{input_category}__{output_category}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.write_csv(out_dir / f"{name}.csv")
    return out_dir


def main() -> None:
    input_category, output_category = "olfaction", "front_leg"
    tables = build_pathway_drilldown(input_category, output_category)
    out_dir = save_pathway_drilldown(input_category, output_category, tables)

    print(f"Pathway drill-down: {input_category} -> {output_category}")
    print(f"Nodes: {tables['nodes'].height}, Edges: {tables['edges'].height}, Paths found: {tables['paths'].height}")
    print(f"Saved -> {out_dir}")

    print("\nrole_group counts:")
    print(tables["nodes"]["role_group"].value_counts().sort("count", descending=True))

    print("\nTop paths by bottleneck weight:")
    with pl.Config(tbl_rows=20, fmt_str_lengths=200):
        print(tables["paths"].head(10))


if __name__ == "__main__":
    main()
