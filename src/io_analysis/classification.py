"""Phase 2: derive io_role / input_category / output_category, exactly per
docs/io_classification_rules.md. Reads the raw node census and writes a
separate derived table (data/io_classification.parquet) - never mutates it.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from io_analysis.load_data import PROJECT_ROOT, load_nodes

CLASSIFICATION_PATH = PROJECT_ROOT / "data" / "io_classification.parquet"

# io_role source: `superclass` only. See docs/io_classification_rules.md section 1.
SENSORY_SUPERCLASSES = [
    "cb_sensory", "ol_sensory", "vnc_sensory",
    "sensory_ascending", "sensory_descending",
]
OPTIC_SUPERCLASSES = ["ol_intrinsic", "visual_projection", "visual_centrifugal"]
MOTOR_SUPERCLASSES = ["vnc_motor", "cb_motor"]
ENDOCRINE_SUPERCLASSES = ["vnc_endocrine", "cb_endocrine"]
OTHER_EFFERENT_SUPERCLASSES = [
    "vnc_efferent", "cb_efferent", "efferent_ascending", "efferent_descending",
]

# Used by input/output_category to decide "not_input"/"not_output" vs "unknown".
OUTPUT_SUPERCLASSES = MOTOR_SUPERCLASSES + ENDOCRINE_SUPERCLASSES + OTHER_EFFERENT_SUPERCLASSES


def add_io_role(nodes: pl.DataFrame) -> pl.DataFrame:
    is_tbc = pl.col("superclass").str.ends_with("_tbc")
    is_ens = pl.col("superclass") == "ENS"
    is_na = pl.col("superclass").is_null()

    role = (
        pl.when(is_na | is_tbc | is_ens).then(pl.lit("unknown"))
        .when(pl.col("superclass").is_in(SENSORY_SUPERCLASSES)).then(pl.lit("sensory_input"))
        .when(pl.col("superclass").is_in(OPTIC_SUPERCLASSES)).then(pl.lit("optic_processing"))
        .when(pl.col("superclass") == "cb_intrinsic").then(pl.lit("central_processing"))
        .when(pl.col("superclass") == "vnc_intrinsic").then(pl.lit("vnc_processing"))
        .when(pl.col("superclass") == "ascending_neuron").then(pl.lit("ascending"))
        .when(pl.col("superclass") == "descending_neuron").then(pl.lit("descending"))
        .when(pl.col("superclass").is_in(MOTOR_SUPERCLASSES)).then(pl.lit("motor_output"))
        .when(pl.col("superclass").is_in(ENDOCRINE_SUPERCLASSES)).then(pl.lit("endocrine_output"))
        .when(pl.col("superclass").is_in(OTHER_EFFERENT_SUPERCLASSES)).then(pl.lit("other_efferent"))
        .otherwise(pl.lit("unknown"))
        .alias("io_role")
    )
    return nodes.with_columns(role)


# input_category source: `class`, only meaningful for sensory-superclass rows.
# See docs/io_classification_rules.md section 2.
INPUT_CATEGORY_BY_CLASS = {
    "visual": "vision",
    "olfactory": "olfaction",
    "gustatory": "gustation",
    "mechanosensory": "mechanosensation",
    "mechanosensory_tactile": "mechanosensation",
    "mechanosensory_proprioceptive": "proprioception",
    "hygrosensory": "hygrosensation",
    "thermosensory": "thermosensation",
    "chemosensory": "other_sensory",
    "unknown_sensory": "unknown",
    "mechanosensory_tbc": "unknown",
}


def add_input_category(nodes: pl.DataFrame) -> pl.DataFrame:
    # .is_in() returns null (not False) for a null superclass; without fill_null
    # these rows would wrongly fall into the "unknown" branch instead of "not_input".
    is_sensory = pl.col("superclass").is_in(SENSORY_SUPERCLASSES).fill_null(False)

    class_branch = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))  # empty seed branch
    for class_val, category in INPUT_CATEGORY_BY_CLASS.items():
        class_branch = class_branch.when(pl.col("class") == class_val).then(pl.lit(category))
    class_branch = class_branch.otherwise(pl.lit("unknown"))  # sensory row, unmapped/NA class

    category = (
        pl.when(~is_sensory).then(pl.lit("not_input"))
        .otherwise(class_branch)
        .alias("input_category")
    )
    return nodes.with_columns(category)


# output_category source, in priority order: for motor rows (vnc_motor/
# cb_motor), `subclass` first - it's a direct motor-target code (fl/ml/hl/
# wm/hm/nm/ad/pm), unlike exitNerve which only tells you which nerve bundle
# a fiber exits through, not which muscle group it drives. exitNerve stays
# the fallback for non-motor efferent/endocrine rows and unmapped subclass
# values am/rm. The explicit unknown-target code xm stays unknown and
# never falls through to the nerve mapping.
# See docs/io_classification_rules.md section 3.

MOTOR_SUBCLASS_TO_CATEGORY = {
    "fl": "front_leg",
    "ml": "middle_leg",
    "hl": "hind_leg",
    "wm": "wing",
    "hm": "haltere",
    "nm": "neck",
    "ad": "abdomen",
    "pm": "proboscis",
}

# exitNerve fallback: which nerve a fiber exits through, not which muscle it
# drives - lower confidence, used only where subclass doesn't resolve it.
# PrN (prosternal nerve) is deliberately left unmapped: T1-neuromere
# membership alone doesn't establish a specific leg target (0 rows affected).
OUTPUT_CATEGORY_BY_EXIT_NERVE = {
    "ProLN": "front_leg", "ProCN": "front_leg", "DProN": "front_leg",
    "VProN": "front_leg", "ProAN": "front_leg",
    "MesoLN": "middle_leg", "MesoAN": "middle_leg",
    "MetaLN": "hind_leg",
    "DMetaN": "haltere",
    "ADMN": "wing", "PDMN": "wing", "PDMNa": "wing", "PDMNp": "wing",
    "CvN": "neck",
    "PhN": "proboscis", "aPhN": "proboscis", "MxLbN": "proboscis",
    "AbN1": "abdomen", "AbN2": "abdomen", "AbN3": "abdomen",
    "AbN4": "abdomen", "AbNT": "abdomen",
    "NCC": "endocrine",
    "AN": "other_motor",
    "ON": "unknown",
    "TBD": "unknown",
}


def add_output_category(nodes: pl.DataFrame) -> pl.DataFrame:
    # Same null-propagation pitfall as add_input_category - see comment there.
    is_output = pl.col("superclass").is_in(OUTPUT_SUPERCLASSES).fill_null(False)
    is_motor = pl.col("superclass").is_in(MOTOR_SUPERCLASSES).fill_null(False)
    is_multi_valued = pl.col("exitNerve").str.contains(",", literal=True).fill_null(False)

    exit_branch = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for nerve_val, category in OUTPUT_CATEGORY_BY_EXIT_NERVE.items():
        exit_branch = exit_branch.when(pl.col("exitNerve") == nerve_val).then(pl.lit(category))
    exit_branch = exit_branch.otherwise(pl.lit("unknown"))  # output row, unmapped/NA exitNerve

    # "xm" is MANC's own explicit "unknown target" code (one of its 8
    # systematic-type subclasses, alongside fl/ml/hl/wm/hm/nm/ad) - it must
    # never fall through to a specific exitNerve-guessed body part, unlike
    # am/rm (not part of that documented scheme, no confirmed meaning either
    # way) which still fall back to exitNerve below.
    is_xm = pl.col("subclass") == "xm"

    subclass_branch = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.Utf8))
    for subclass_val, category in MOTOR_SUBCLASS_TO_CATEGORY.items():
        subclass_branch = subclass_branch.when(pl.col("subclass") == subclass_val).then(pl.lit(category))
    subclass_branch = (
        subclass_branch.when(is_xm).then(pl.lit("unknown"))
        .otherwise(exit_branch)  # unmapped motor subclass - fall back to exitNerve
    )

    category = (
        pl.when(~is_output).then(pl.lit("not_output"))
        .when(is_multi_valued).then(pl.lit("unknown"))
        .when(is_motor).then(subclass_branch)
        .otherwise(exit_branch)
        .alias("output_category")
    )
    return nodes.with_columns(category)


def build_classification(nodes: pl.DataFrame | None = None) -> pl.DataFrame:
    """Return bodyid + io_role + input_category + output_category only.
    Join back to load_nodes() by bodyid when raw fields are needed.
    """
    if nodes is None:
        nodes = load_nodes()
    classified = add_io_role(nodes)
    classified = add_input_category(classified)
    classified = add_output_category(classified)
    return classified.select("bodyid", "io_role", "input_category", "output_category")


def save_classification(classification: pl.DataFrame, path: Path = CLASSIFICATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    classification.write_parquet(path, compression="zstd")


def main() -> None:
    nodes = load_nodes()
    classification = build_classification(nodes)
    save_classification(classification)

    n_total = classification.height
    print(f"Classified {n_total} nodes -> {CLASSIFICATION_PATH}")

    print("\nio_role counts:")
    print(classification["io_role"].value_counts().sort("count", descending=True))

    print("\ninput_category counts (excluding not_input):")
    print(
        classification.filter(pl.col("input_category") != "not_input")["input_category"]
        .value_counts().sort("count", descending=True)
    )

    print("\noutput_category counts (excluding not_output):")
    print(
        classification.filter(pl.col("output_category") != "not_output")["output_category"]
        .value_counts().sort("count", descending=True)
    )

    input_n = classification.filter(pl.col("io_role") == "sensory_input").height
    output_n = classification.filter(
        pl.col("io_role").is_in(["motor_output", "endocrine_output", "other_efferent"])
    ).height
    unknown_n = classification.filter(pl.col("io_role") == "unknown").height
    print(f"\ninput={input_n} ({100*input_n/n_total:.1f}%)  "
          f"output={output_n} ({100*output_n/n_total:.1f}%)  "
          f"unknown={unknown_n} ({100*unknown_n/n_total:.1f}%)")
    print("(cross-check: these should match r/build_io_census.R's provisional tally)")


if __name__ == "__main__":
    main()
