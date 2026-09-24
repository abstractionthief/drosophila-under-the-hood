"""Regression checks for browser exports and classification provenance."""

import json

import polars as pl
import pytest

from io_analysis import export_app_data as exporter
from io_analysis import pathways


def test_coverage_keeps_unknown_outputs_separate(monkeypatch):
    nodes = pl.DataFrame({
        "bodyid": list(range(1, 8)),
        "status": ["Traced"] * 7,
        "statusLabel": ["Reviewed"] * 7,
        "superclass": ["vnc_motor", "vnc_endocrine", "cb_motor", "vnc_motor",
                       "vnc_motor", "vnc_motor", "cb_intrinsic"],
        "class": pl.Series([None] * 7, dtype=pl.String),
        "subclass": ["nm", None, "am", "xm", "wm", None, None],
        "exitNerve": ["DProN", "NCC", "AN", "DMetaN", "ADMN,MesoAN", None, None],
    })
    monkeypatch.setattr(exporter, "load_nodes", lambda: nodes)
    coverage = exporter.export_coverage()
    assert coverage["output_category_total"] == 6
    assert coverage["output_category_subclass_derived"] == 1
    assert coverage["output_category_exit_nerve_fallback"] == 2
    assert coverage["output_category_unknown"] == 3


def test_rule_hash_changes_when_override_logic_changes(monkeypatch, tmp_path):
    source = tmp_path / "classification.py"
    monkeypatch.setattr(exporter.classification_module, "__file__", str(source))
    source.write_text('MAPPING = {"wm": "wing"}\nis_xm = subclass == "xm"\n')
    original = exporter.classification_rule_hash()
    # The mapping stays identical; the old dictionaries-only hash missed this.
    source.write_text('MAPPING = {"wm": "wing"}\nis_xm = False\n')
    assert exporter.classification_rule_hash() != original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_export_rejects_nonfinite_values_without_overwriting(tmp_path, value):
    target = tmp_path / "matrix.json"
    target.write_text('{"previous": true}')
    with pytest.raises(ValueError):
        exporter.write_json(target, {"cells": [{"metric": value}]})
    assert json.loads(target.read_text()) == {"previous": True}


def test_matrix_export_updates_csv_with_normalized_and_undefined_values(monkeypatch, tmp_path):
    matrix = pl.DataFrame({
        "input_category": ["olfaction", "olfaction"],
        "output_category": ["front_leg", "wing"],
        "max_flow": [3, 0],
        "max_flow_frac_of_input_output": [0.5, 0.0],
        "max_flow_frac_of_output_input": [1.0, None],
    })
    monkeypatch.setattr(exporter, "build_io_matrix", lambda: matrix)
    save = exporter.save_matrix
    target = tmp_path / "io_matrix.csv"
    monkeypatch.setattr(exporter, "save_matrix", lambda table: save(table, target))
    payload = exporter.export_matrix()
    assert pl.read_csv(target).to_dicts() == payload["cells"]
    assert json.loads(json.dumps(payload, allow_nan=False))["cells"][1]["max_flow_frac_of_output_input"] is None


def test_pathway_export_refreshes_existing_csv_example(monkeypatch, tmp_path):
    csv_dir = tmp_path / "csv"
    example = csv_dir / "olfaction__front_leg"
    example.mkdir(parents=True)
    (example / "edges.csv").write_text("source,target,weight\n99,100,1\n")
    tables = {
        "nodes": pl.DataFrame({"bodyid": [1, 2]}),
        "edges": pl.DataFrame({"source": [1], "target": [2], "weight": [5]}),
        "paths": pl.DataFrame({"path": ["1->2"], "hops": [1]}),
    }
    monkeypatch.setattr(exporter, "INPUT_CATEGORIES", ["olfaction"])
    monkeypatch.setattr(exporter, "OUTPUT_CATEGORIES", ["front_leg"])
    monkeypatch.setattr(exporter, "PATHWAYS_OUT_DIR", tmp_path / "json")
    monkeypatch.setattr(exporter, "PATHWAYS_DIR", csv_dir)
    monkeypatch.setattr(pathways, "PATHWAYS_DIR", csv_dir)
    monkeypatch.setattr(exporter, "load_graph_context", lambda: (None, None))
    monkeypatch.setattr(exporter, "build_pathway_drilldown", lambda *args, **kwargs: tables)
    assert exporter.export_pathways() == ["olfaction__front_leg.json"]
    payload = json.loads((tmp_path / "json" / "olfaction__front_leg.json").read_text())
    for name in tables:
        assert pl.read_csv(example / f"{name}.csv").to_dicts() == payload[name]
