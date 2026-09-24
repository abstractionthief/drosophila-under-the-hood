"""Export a full-census search index (all 165,122 Traced neurons, not just
the ~6,748 reachable via a pathway drill-down) for the app's global search.
Records each neuron's first pathway match, if any, so the frontend can
distinguish an interactive result from a metadata-only one.
"""

from __future__ import annotations

import json

import polars as pl

from io_analysis.classification import build_classification
from io_analysis.load_data import PROJECT_ROOT, load_nodes

PATHWAYS_DIR = PROJECT_ROOT / "app" / "data" / "pathways"
OUT_PATH = PROJECT_ROOT / "app" / "data" / "search_index.json"


def build_pathway_lookup() -> dict[int, str]:
    """bodyid -> the first pathway key (input__output) it appears in."""
    lookup: dict[int, str] = {}
    for f in sorted(PATHWAYS_DIR.glob("*.json")):
        pathway_key = f.stem
        data = json.loads(f.read_text())
        for node in data.get("nodes", []):
            bodyid = node.get("bodyid")
            if bodyid is not None and bodyid not in lookup:
                lookup[bodyid] = pathway_key
    return lookup


def main() -> None:
    nodes = load_nodes().filter(pl.col("status") == "Traced")
    classification = build_classification(load_nodes())
    merged = nodes.join(classification, on="bodyid", how="left").select(
        "bodyid", "type", "name", "superclass", "class",
        "io_role", "input_category", "output_category",
    )

    pathway_lookup = build_pathway_lookup()
    pathway_col = [pathway_lookup.get(b) for b in merged["bodyid"].to_list()]
    merged = merged.with_columns(pl.Series("pathway_key", pathway_col))

    index = {col: merged[col].to_list() for col in merged.columns}
    OUT_PATH.write_text(json.dumps(index))

    n_reachable = sum(1 for p in pathway_col if p is not None)
    print(f"Exported {merged.height} neurons ({n_reachable} reachable via a pathway drill-down) -> {OUT_PATH}")
    print(f"File size: {OUT_PATH.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
