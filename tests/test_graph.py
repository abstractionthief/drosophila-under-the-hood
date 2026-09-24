"""Small hand-computable directed graph, checked against graph.py's metrics
directly (not the real 165k-neuron dataset) - a correctness check on the
algorithms themselves, independent of any classification/data question.
"""

import json

import numpy as np
import scipy.sparse as sp

import io_analysis.graph as graph_module
from io_analysis.graph import (
    NeuronGraph,
    compute_category_synaptic_totals,
    compute_max_flow,
    compute_pairwise_hop_counts,
    compute_pooled_metrics,
)

# 4 nodes: 0 (input, category "olfaction"), 1/2 (processing, no category),
# 3 (output, category "front_leg"). Edges: 0->1 (5), 1->2 (3), 2->3 (2),
# and a direct 0->3 (1) - so there are two source->target routes of
# different length and weight.


def _tiny_graph() -> NeuronGraph:
    n = 4
    rows = [0, 1, 2, 0]
    cols = [1, 2, 3, 3]
    weights = np.array([5, 3, 2, 1], dtype=np.int32)
    adjacency = sp.csr_matrix((weights, (rows, cols)), shape=(n, n))
    cost = sp.csr_matrix((1.0 / weights, (rows, cols)), shape=(n, n))
    return NeuronGraph(
        n=n,
        adjacency=adjacency,
        cost=cost,
        reverse_adjacency=adjacency.transpose().tocsr(),
        idx_to_bodyid=np.array([100, 101, 102, 103]),
        input_category=np.array(["olfaction", "not_input", "not_input", "not_input"]),
        output_category=np.array(["not_output", "not_output", "not_output", "front_leg"]),
    )


def test_pooled_metrics_reachability_and_shortest_paths():
    graph = _tiny_graph()
    df = compute_pooled_metrics(graph)
    row = df.filter((df["input_category"] == "olfaction") & (df["output_category"] == "front_leg")).row(0, named=True)
    assert row["reachable"] is True
    # unweighted BFS: the direct 0->3 edge is 1 hop, shorter than 0->1->2->3 (3 hops)
    assert row["shortest_path_hops"] == 1.0
    # weighted (cost=1/weight): direct edge cost=1/1=1.0, vs 1/5+1/3+1/2≈1.033 - still the direct edge
    assert abs(row["weighted_shortest_path"] - 1.0) < 1e-9


def test_pairwise_hop_counts_exact_pair_within_limit():
    graph = _tiny_graph()
    counts = compute_pairwise_hop_counts(graph, max_hops=1)
    # only the direct 1-hop route counts when max_hops=1
    assert counts[("olfaction", "front_leg")] == 1

    counts_wide = compute_pairwise_hop_counts(graph, max_hops=3)
    # still exactly one (input, output) neuron pair, regardless of how many
    # distinct paths connect them - this counts neuron pairs, not paths
    assert counts_wide[("olfaction", "front_leg")] == 1


def test_max_flow_sums_both_routes():
    graph = _tiny_graph()
    flows = compute_max_flow(graph)
    # direct edge capacity 1, plus the 0->1->2->3 route bottlenecked at
    # min(5,3,2)=2 - both routes are node-disjoint except at the endpoints,
    # so max-flow should sum them: 1 + 2 = 3
    assert flows[("olfaction", "front_leg")] == 3


def test_category_synaptic_totals_are_the_normalization_denominators():
    # node 0 (olfaction)'s total outgoing weight: 0->1 (5) + 0->3 (1) = 6
    # node 3 (front_leg)'s total incoming weight: 2->3 (2) + 0->3 (1) = 3
    graph = _tiny_graph()
    presynaptic_total, postsynaptic_total = compute_category_synaptic_totals(graph)
    assert presynaptic_total["olfaction"] == 6
    assert postsynaptic_total["front_leg"] == 3
    # max_flow(olfaction, front_leg) = 3, so the normalized fractions a
    # reviewer asked for (raw max-flow favors large categories) should be
    # 3/6 = 0.5 of olfaction's total output, and 3/3 = 1.0 of front_leg's
    # total input - both comparable across category sizes, unlike raw max_flow.
    assert presynaptic_total["olfaction"] > 0 and postsynaptic_total["front_leg"] > 0


def test_normalized_max_flow_uses_null_for_zero_capacity(monkeypatch):
    # The olfactory source can reach one processing neuron, but the motor
    # output and a second sensory category have no incident connections.
    # Present-but-disconnected and entirely absent output categories must
    # serialize as valid JSON instead of allowing 0/0 NaN through export.
    adjacency = sp.csr_matrix((np.array([1], dtype=np.int32), ([0], [1])), shape=(4, 4))
    graph = NeuronGraph(
        n=4, adjacency=adjacency, cost=adjacency.astype(float),
        reverse_adjacency=adjacency.transpose().tocsr(), idx_to_bodyid=np.arange(4),
        input_category=np.array(["olfaction", "not_input", "not_input", "vision"]),
        output_category=np.array(["not_output", "not_output", "front_leg", "not_output"]),
    )
    monkeypatch.setattr(graph_module, "build_graph", lambda: graph)
    rows = graph_module.build_io_matrix().to_dicts()
    for row in rows:
        assert row["max_flow"] == 0
        assert row["max_flow_frac_of_output_input"] is None
        if row["input_category"] == "olfaction":
            assert row["max_flow_frac_of_input_output"] == 0.0
        else:
            assert row["max_flow_frac_of_input_output"] is None
    assert json.loads(json.dumps(rows, allow_nan=False)) == rows


def test_normalized_max_flow_retains_defined_fractions(monkeypatch):
    monkeypatch.setattr(graph_module, "build_graph", _tiny_graph)
    rows = graph_module.build_io_matrix().to_dicts()
    pair = next(row for row in rows if row["output_category"] == "front_leg")
    assert pair["max_flow_frac_of_input_output"] == 0.5
    assert pair["max_flow_frac_of_output_input"] == 1.0
