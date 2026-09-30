"""Check the traversal's population and round semantics on a recurrent graph."""

import numpy as np
from scipy.sparse import csr_matrix

from io_analysis.primer_stats import traversal


def test_traversal_uses_previous_round_and_reports_unreached_neurons():
    # 0 -> 1 -> 2 <-> 3; an unreachable 4 <-> 5 component also feeds 1.
    # Node 6 has no input. At 40%, the 0 -> 1 input reaches the boundary.
    incoming = csr_matrix(
        ([2, 3, 1, 1, 1, 1, 1], ([1, 1, 2, 2, 3, 4, 5], [0, 4, 1, 3, 2, 5, 4])),
        shape=(7, 7),
    )
    seeds = np.array([True, False, False, False, False, False, False])
    roles = np.array(["sensory_input", "descending", "central_processing", "motor_output",
                      "central_processing", "central_processing", "motor_output"])

    result = traversal(incoming, seeds, roles, 40)
    assert result["layer_counts_including_seeds"] == [1, 1, 1, 1]
    assert result["nonseed_neurons"] == {
        "population_count": 6, "reached_count": 3, "unreached_count": 3,
        "median_layer_among_reached": 2.0, "deepest_reached_layer": 3,
    }
    assert result["descending_neurons"]["median_layer_among_reached"] == 1.0
    assert result["motor_neurons"]["reached_count"] == 1
    assert result["motor_neurons"]["unreached_count"] == 1

    # Raising the threshold prevents entry into the whole reachable chain.
    blocked = traversal(incoming, seeds, roles, 60)
    assert blocked["nonseed_neurons"]["reached_count"] == 0
    assert blocked["nonseed_neurons"]["median_layer_among_reached"] is None
