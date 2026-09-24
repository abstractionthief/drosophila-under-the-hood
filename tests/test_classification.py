"""Regression tests for classification.py, focused on the output_category
bug an external review found: exitNerve-only mapping disagreed with the
motor neuron's own documented subclass label for real neurons (e.g. 20
DProN/nm neck-motor neurons were classified front_leg). See
docs/io_classification_rules.md section 3 and docs/project_log.md section 23c.
"""

import polars as pl

from io_analysis.classification import add_output_category

SCHEMA = {"bodyid": pl.Int64, "superclass": pl.Utf8, "exitNerve": pl.Utf8, "subclass": pl.Utf8}


def _nodes(rows):
    return pl.DataFrame(rows, schema=SCHEMA)


def test_motor_subclass_takes_priority_over_exit_nerve():
    # DProN alone would map to front_leg (T1 leg nerve); subclass "nm"
    # (neck motor) must win instead. This is the exact disagreement the
    # review found on 20 real neurons.
    nodes = _nodes([{"bodyid": 1, "superclass": "vnc_motor", "exitNerve": "DProN", "subclass": "nm"}])
    assert add_output_category(nodes)["output_category"][0] == "neck"


def test_motor_subclass_haltere_no_longer_excluded():
    # Before the fix, every annotated haltere motor neuron (exitNerve=AbN1,
    # subclass=hm) was classified "abdomen" via the exitNerve-only rule.
    nodes = _nodes([{"bodyid": 2, "superclass": "vnc_motor", "exitNerve": "AbN1", "subclass": "hm"}])
    assert add_output_category(nodes)["output_category"][0] == "haltere"


def test_motor_unmapped_subclass_falls_back_to_exit_nerve():
    # "am"/"rm" aren't part of MANC's documented subclass scheme and have no
    # confirmed meaning either way - fall back to the exitNerve table.
    nodes = _nodes([{"bodyid": 3, "superclass": "vnc_motor", "exitNerve": "AN", "subclass": "am"}])
    assert add_output_category(nodes)["output_category"][0] == "other_motor"


def test_motor_xm_subclass_is_unknown_not_exit_nerve_guessed():
    # "xm" is MANC's own explicit "unknown target" code - it must never
    # fall through to exitNerve for a specific (wrong) body-part guess.
    # A second-round review caught this: DMetaN/PDMNa exitNerve would
    # otherwise resolve xm rows to "haltere"/"wing" respectively.
    nodes = _nodes([
        {"bodyid": 10, "superclass": "vnc_motor", "exitNerve": "DMetaN", "subclass": "xm"},
        {"bodyid": 11, "superclass": "vnc_motor", "exitNerve": "PDMNa", "subclass": "xm"},
    ])
    result = add_output_category(nodes)
    assert result["output_category"].to_list() == ["unknown", "unknown"]


def test_non_motor_efferent_uses_exit_nerve_directly():
    # subclass-first only applies to vnc_motor/cb_motor; endocrine rows
    # never have a motor-subclass code and must ignore this branch.
    nodes = _nodes([{"bodyid": 4, "superclass": "vnc_endocrine", "exitNerve": "NCC", "subclass": None}])
    assert add_output_category(nodes)["output_category"][0] == "endocrine"


def test_non_output_superclass_is_not_output():
    nodes = _nodes([{"bodyid": 5, "superclass": "cb_intrinsic", "exitNerve": None, "subclass": None}])
    assert add_output_category(nodes)["output_category"][0] == "not_output"


def test_prn_is_left_unmapped_not_guessed():
    # PrN was previously force-mapped to front_leg on an unsound rationale
    # (T1-neuromere membership alone doesn't establish a leg target) -
    # must now fall through to "unknown", not a specific body part.
    nodes = _nodes([{"bodyid": 6, "superclass": "vnc_motor", "exitNerve": "PrN", "subclass": None}])
    assert add_output_category(nodes)["output_category"][0] == "unknown"


def test_multi_valued_exit_nerve_is_unknown_even_with_motor_subclass():
    nodes = _nodes([{"bodyid": 7, "superclass": "vnc_motor", "exitNerve": "ADMN,MesoAN", "subclass": "wm"}])
    assert add_output_category(nodes)["output_category"][0] == "unknown"
