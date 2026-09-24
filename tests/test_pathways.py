"""Regression test for the pathway-pruning bug an external review found:
select_relevant_nodes() used to truncate candidate nodes purely by lowest
combined hop-distance, with no guarantee any single complete route
survived the max_nodes cap - ties got resolved by array index, not by
path membership. Confirmed on the real dataset: 16 of 80 exported pathway
pairs had an empty paths table despite the whole-graph matrix reporting
them reachable. See docs/project_log.md section 23c.
"""

import numpy as np
import polars as pl
import scipy.sparse as sp

from io_analysis.graph import NeuronGraph
from io_analysis.pathways import build_induced_edges, find_top_paths, select_relevant_nodes


def _line_graph() -> NeuronGraph:
    # source(0) -> mid(1) -> target(2), a single 2-hop path and nothing else.
    # All three nodes tie at total_hops=2 when max_hops=2, so a naive
    # "closest max_nodes nodes" truncation with max_nodes=1 keeps only
    # node 0 (lowest index) and drops the path entirely.
    n = 3
    weights = np.array([10, 10], dtype=np.int32)
    adjacency = sp.csr_matrix((weights, ([0, 1], [1, 2])), shape=(n, n))
    cost = sp.csr_matrix((1.0 / weights, ([0, 1], [1, 2])), shape=(n, n))
    return NeuronGraph(
        n=n,
        adjacency=adjacency,
        cost=cost,
        reverse_adjacency=adjacency.transpose().tocsr(),
        idx_to_bodyid=np.array([10, 11, 12]),
        input_category=np.array(["olfaction", "not_input", "not_input"]),
        output_category=np.array(["not_output", "not_output", "front_leg"]),
    )


def test_tight_max_nodes_cap_still_preserves_a_complete_path():
    graph = _line_graph()
    # max_nodes=1 is deliberately smaller than the 3 nodes the only path
    # needs - without forced-path preservation this returns just node 0
    # and the induced subgraph has zero edges.
    relevant = select_relevant_nodes(
        graph, "olfaction", "front_leg", max_hops=2, minimum_weight=1, max_nodes=1
    )
    assert set(relevant) == {0, 1, 2}, "the only complete route must survive even under an absurdly tight cap"

    edges = build_induced_edges(graph, minimum_weight=1, relevant_idx=relevant)
    assert edges.height == 2

    paths = find_top_paths(
        graph, edges, "olfaction", "front_leg", relevant_idx=relevant, max_hops=2, top_n_paths=5
    )
    assert paths.height >= 1, "a real 2-hop path exists and must appear in the paths table"


def test_generous_max_nodes_cap_is_a_no_op():
    graph = _line_graph()
    relevant = select_relevant_nodes(
        graph, "olfaction", "front_leg", max_hops=2, minimum_weight=1, max_nodes=150
    )
    assert set(relevant) == {0, 1, 2}
