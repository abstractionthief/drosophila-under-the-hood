"""Sampling and projection rules behind the Start Here animation."""

import numpy as np
import polars as pl
import pytest

from io_analysis import export_start_animation

from io_analysis.export_start_animation import COORD_SCALE, ROLE_QUOTA, WAVES, normalize_xy, sample_indices


@pytest.mark.parametrize("column", ["source", "target"])
@pytest.mark.parametrize("missing_id", [5, 20, 50])
def test_build_rejects_unknown_edge_endpoints(monkeypatch, column, missing_id):
    nodes = pl.DataFrame({"bodyid": [10, 30, 40], "status": ["Traced"] * 3})
    classified = nodes.with_columns(
        pl.lit("sensory_input").alias("io_role"),
        pl.lit("vision").alias("input_category"),
    )
    edge = {"source": [10], "target": [30], "weight": [1]}
    edge[column] = [missing_id]
    monkeypatch.setattr(export_start_animation, "load_nodes", lambda: nodes)
    monkeypatch.setattr(export_start_animation, "build_classification", lambda _: classified)
    monkeypatch.setattr(export_start_animation, "load_edges", lambda: pl.DataFrame(edge))
    with pytest.raises(ValueError, match="endpoint is not a Traced neuron"):
        export_start_animation.build()


def test_projection_keeps_equal_scale_and_bounds():
    x = np.linspace(0, 300, 1001)
    y = np.linspace(0, 100, 1001)
    nx, ny, aspect = normalize_xy(x, y)
    assert nx.min() >= 0 and nx.max() <= COORD_SCALE
    assert ny.min() >= 0 and ny.max() <= COORD_SCALE / aspect + 1
    assert abs(aspect - 3.0) < 1e-9
    # equal scale: a step in x and the same step in y map to the same distance
    assert abs((nx[-1] - nx[0]) / 300 - (ny[-1] - ny[0]) / 100) < 0.05


def test_sampling_is_deterministic_and_respects_quotas():
    roles = np.array(["optic_processing"] * 5000 + ["descending"] * 40 + ["sensory_input"] * 500)
    categories = np.array(["not_input"] * 5040 + [m for m, _ in WAVES] * 100)
    first = sample_indices(roles, categories, np.random.default_rng(0))
    again = sample_indices(roles, categories, np.random.default_rng(0))
    assert np.array_equal(first, again)
    assert (roles[first] == "optic_processing").sum() == ROLE_QUOTA["optic_processing"]
    assert (roles[first] == "descending").sum() == 40  # small pools are taken whole
    per_modality = ROLE_QUOTA["sensory_input"] // len(WAVES)
    for modality, _ in WAVES:
        assert (categories[first] == modality).sum() == min(per_modality, 100)


def test_exported_seed_counts_match_layer_zero():
    """The app's caption relies on sampled_seed_count; layer 0 is exactly the seeds."""
    import json
    from io_analysis.export_start_animation import OUT_PATH

    data = json.loads(OUT_PATH.read_text())
    for wave in data["waves"]:
        assert wave["sampled_seed_count"] == sum(1 for layer in wave["layer"] if layer == 0)
