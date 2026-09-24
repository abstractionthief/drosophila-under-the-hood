"""Export soma position + io_role for every traced neuron as columnar JSON
for the app's Anatomy view. Real EM coordinates instead of a force-directed
layout, which isn't feasible at 165k nodes (see graph.py).
"""

from __future__ import annotations

import json

import polars as pl

from io_analysis.classification import build_classification
from io_analysis.load_data import PROJECT_ROOT, load_nodes

POSITIONS_PATH = PROJECT_ROOT / "data" / "io_neuron_positions.csv"
OUT_PATH = PROJECT_ROOT / "app" / "data" / "positions.json"


def main() -> None:
    if not POSITIONS_PATH.exists():
        raise FileNotFoundError(f"{POSITIONS_PATH} not found - run r/build_neuron_positions.R first.")

    positions = pl.read_csv(POSITIONS_PATH).with_columns(pl.col("bodyid").cast(pl.Int64))
    nodes = load_nodes()
    classification = build_classification(nodes)

    joined = positions.join(classification.select("bodyid", "io_role"), on="bodyid", how="left")
    joined = joined.with_columns(pl.col("io_role").fill_null("unknown"))

    payload = {
        "n": joined.height,
        "bodyid": joined["bodyid"].to_list(),
        "x": joined["x"].to_list(),
        "y": joined["y"].to_list(),
        "z": joined["z"].to_list(),
        "io_role": joined["io_role"].to_list(),
        "coverage_note": (
            f"{joined.height} of the census' Traced neurons have a soma position; "
            "neurons without one (e.g. severed/fragment somas) are omitted here, not "
            "hidden elsewhere in the project."
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload))
    print(f"Exported {joined.height} neuron positions -> {OUT_PATH}")
    print(joined["io_role"].value_counts().sort("count", descending=True))


if __name__ == "__main__":
    main()
