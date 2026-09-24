"""Boundary-validation tests for load_data.py, added after a domain review
noted that load_data.py cast columns but didn't enforce required columns,
bodyid/edge uniqueness, positive weights, or manifest/data agreement -
exactly the kind of real pipeline failure mode (a stale manifest, a bad
re-extraction) these protect against, not just algorithm edge cases.
"""

import json

import polars as pl
import pytest

import io_analysis.load_data as load_data
from io_analysis.load_data import validate_edges, validate_edges_manifest, validate_nodes


def test_validate_nodes_accepts_well_formed_data():
    nodes = pl.DataFrame({
        "bodyid": [1, 2, 3], "status": ["Traced"] * 3, "superclass": ["cb_motor"] * 3,
        "class": [None, None, None], "subclass": ["ad", "ad", "ad"], "exitNerve": ["AbN1"] * 3,
    })
    validate_nodes(nodes)  # must not raise


def test_validate_nodes_rejects_missing_column():
    nodes = pl.DataFrame({"bodyid": [1, 2]})
    with pytest.raises(ValueError, match="missing required column"):
        validate_nodes(nodes)


def test_validate_nodes_rejects_duplicate_bodyid():
    nodes = pl.DataFrame({
        "bodyid": [1, 1], "status": ["Traced"] * 2, "superclass": ["cb_motor"] * 2,
        "class": [None, None], "subclass": ["ad"] * 2, "exitNerve": ["AbN1"] * 2,
    })
    with pytest.raises(ValueError, match="duplicate bodyid"):
        validate_nodes(nodes)


def test_validate_nodes_rejects_null_bodyid():
    nodes = pl.DataFrame({
        "bodyid": [1, None], "status": ["Traced"] * 2, "superclass": ["cb_motor"] * 2,
        "class": [None, None], "subclass": ["ad"] * 2, "exitNerve": ["AbN1"] * 2,
    })
    with pytest.raises(ValueError, match="null bodyid"):
        validate_nodes(nodes)


def test_validate_edges_accepts_well_formed_data():
    edges = pl.DataFrame({"source": [1, 2], "target": [2, 3], "weight": [5, 10]})
    validate_edges(edges)  # must not raise


def test_validate_edges_rejects_nonpositive_weight():
    edges = pl.DataFrame({"source": [1], "target": [2], "weight": [0]})
    with pytest.raises(ValueError, match="non-positive weight"):
        validate_edges(edges)


def test_validate_edges_rejects_duplicate_source_target():
    # The exact failure mode a domain review flagged: scipy.sparse sums
    # duplicate adjacency entries but a separately-built 1/weight cost
    # matrix would sum 1/w1 + 1/w2, not 1/(w1+w2) - the two would disagree.
    edges = pl.DataFrame({"source": [1, 1], "target": [2, 2], "weight": [5, 3]})
    with pytest.raises(ValueError, match="duplicate"):
        validate_edges(edges)


def test_validate_edges_manifest_rejects_wrong_dataset():
    edges = pl.DataFrame({"source": [1], "target": [2], "weight": [1]})
    with pytest.raises(ValueError, match="dataset"):
        validate_edges_manifest(edges, {"dataset": "some-other-dataset:v2"})


def test_validate_edges_manifest_rejects_row_count_mismatch():
    edges = pl.DataFrame({"source": [1, 2], "target": [2, 3], "weight": [1, 1]})
    with pytest.raises(ValueError, match="row_count"):
        validate_edges_manifest(edges, {"dataset": "male-cns:v1.0", "row_count": 999})


def test_validate_edges_manifest_accepts_matching_data():
    edges = pl.DataFrame({"source": [1, 2], "target": [2, 3], "weight": [1, 1]})
    validate_edges_manifest(edges, {"dataset": "male-cns:v1.0", "row_count": 2})  # must not raise


def _node_table(bodyids):
    return pl.DataFrame({
        "bodyid": bodyids,
        "status": ["Traced"] * len(bodyids),
        "superclass": ["vnc_motor"] * len(bodyids),
        "class": [None] * len(bodyids),
        "subclass": ["fl"] * len(bodyids),
        "exitNerve": ["ProLN"] * len(bodyids),
    })


def _write_nodes(monkeypatch, tmp_path, nodes):
    path = tmp_path / "nodes.csv"
    nodes.write_csv(path, null_value="NA")
    monkeypatch.setattr(load_data, "NODES_PATH", path)


def _write_edges(monkeypatch, tmp_path, edges, manifest=None):
    path = tmp_path / "edges.parquet"
    edges.write_parquet(path)
    manifest_path = tmp_path / "manifest.json"
    if manifest is None:
        manifest = {"dataset": "male-cns:v1.0", "row_count": edges.height}
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(load_data, "EDGES_PATH", path)
    monkeypatch.setattr(load_data, "EDGES_MANIFEST_PATH", manifest_path)


@pytest.mark.parametrize("bodyids", [[100000.0, 100001.0], [1, 2**63 - 1]])
def test_node_loader_preserves_valid_integer_ids(monkeypatch, tmp_path, bodyids):
    _write_nodes(monkeypatch, tmp_path, _node_table(bodyids))
    result = load_data.load_nodes()
    assert result["bodyid"].dtype == pl.Int64
    assert result["bodyid"].to_list() == [int(value) for value in bodyids]


@pytest.mark.parametrize("value, error", [
    (None, "null bodyid"),
    (float("nan"), "non-finite"),
    (float("inf"), "non-finite"),
    (float("-inf"), "non-finite"),
    (1.9, "fractional"),
    (0, "non-positive"),
    (-1, "non-positive"),
    (float(2**63), "maximum"),
    ("invalid", "numeric integer"),
])
def test_node_loader_rejects_invalid_ids_before_cast(monkeypatch, tmp_path, value, error):
    _write_nodes(monkeypatch, tmp_path, _node_table([value]))
    with pytest.raises(ValueError, match=error):
        load_data.load_nodes()


@pytest.mark.parametrize("loader", ["nodes", "edges"])
def test_loaders_check_required_columns_before_cast(monkeypatch, tmp_path, loader):
    if loader == "nodes":
        _write_nodes(monkeypatch, tmp_path, _node_table([1]).drop("bodyid"))
        load = load_data.load_nodes
    else:
        _write_edges(monkeypatch, tmp_path, pl.DataFrame({"source": [1], "target": [2]}))
        load = load_data.load_edges
    with pytest.raises(ValueError, match="missing required column"):
        load()


def test_edge_loader_accepts_integer_valued_r_floats(monkeypatch, tmp_path):
    _write_edges(monkeypatch, tmp_path, pl.DataFrame({
        "source": [100000.0], "target": [100001.0], "weight": [3.0],
    }))
    result = load_data.load_edges()
    assert result.schema == {"source": pl.Int64, "target": pl.Int64, "weight": pl.Int64}
    assert result.to_dicts() == [{"source": 100000, "target": 100001, "weight": 3}]


@pytest.mark.parametrize("column", ["source", "target", "weight"])
@pytest.mark.parametrize("value, error", [
    (None, "null"),
    (float("nan"), "non-finite"),
    (float("inf"), "non-finite"),
    (float("-inf"), "non-finite"),
    (1.9, "fractional"),
    (0, "non-positive"),
    (-1, "non-positive"),
    ("invalid", "numeric integer"),
])
def test_edge_loader_rejects_invalid_values_before_cast(monkeypatch, tmp_path, column, value, error):
    columns = {"source": [1], "target": [2], "weight": [3]}
    columns[column] = [value]
    _write_edges(monkeypatch, tmp_path, pl.DataFrame(columns))
    with pytest.raises(ValueError, match=error):
        load_data.load_edges()


@pytest.mark.parametrize("column, maximum", [
    ("source", 2**63 - 1), ("target", 2**63 - 1), ("weight", 2**31 - 1),
])
def test_edge_loader_enforces_integer_storage_bounds(monkeypatch, tmp_path, column, maximum):
    columns = {"source": [1], "target": [2], "weight": [3]}
    columns[column] = [maximum]
    _write_edges(monkeypatch, tmp_path, pl.DataFrame(columns))
    assert load_data.load_edges()[column][0] == maximum

    columns[column] = [maximum + 1]
    _write_edges(monkeypatch, tmp_path, pl.DataFrame(columns))
    with pytest.raises(ValueError, match="maximum"):
        load_data.load_edges()


@pytest.mark.parametrize("manifest, error", [
    ({"dataset": "wrong:v2", "row_count": 1}, "dataset"),
    ({"dataset": "male-cns:v1.0", "row_count": 999}, "row_count"),
    ({"dataset": "male-cns:v1.0"}, "row_count"),
])
def test_edge_loader_enforces_manifest_on_normal_load(monkeypatch, tmp_path, manifest, error):
    _write_edges(monkeypatch, tmp_path, pl.DataFrame({"source": [1], "target": [2], "weight": [3]}), manifest)
    with pytest.raises(ValueError, match=error):
        load_data.load_edges()


def test_edge_loader_requires_manifest(monkeypatch, tmp_path):
    _write_edges(monkeypatch, tmp_path, pl.DataFrame({"source": [1], "target": [2], "weight": [3]}))
    monkeypatch.setattr(load_data, "EDGES_MANIFEST_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError, match="missing.json"):
        load_data.load_edges()
