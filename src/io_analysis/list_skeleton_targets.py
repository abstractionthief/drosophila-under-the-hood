"""List the bodyids that need a fetched skeleton: only neurons appearing in
the precomputed pathway drill-downs (`app/data/pathways/*.json`), not all
165k traced neurons - r/build_neuron_skeletons.R fetches just this set.
"""

from __future__ import annotations

import json

from io_analysis.load_data import PROJECT_ROOT

PATHWAYS_DIR = PROJECT_ROOT / "app" / "data" / "pathways"
OUT_PATH = PROJECT_ROOT / "data" / "skeleton_bodyids.csv"


def list_bodyids() -> list[int]:
    files = sorted(PATHWAYS_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError(
            f"No pathway files found in {PATHWAYS_DIR} - run "
            "`uv run python -m io_analysis.export_app_data` first."
        )
    ids: set[int] = set()
    for f in files:
        data = json.loads(f.read_text())
        for node in data.get("nodes", []):
            if "bodyid" in node:
                ids.add(int(node["bodyid"]))
    return sorted(ids)


def main() -> None:
    ids = list_bodyids()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as fh:
        fh.write("bodyid\n")
        fh.writelines(f"{i}\n" for i in ids)
    print(f"{len(ids)} distinct bodyids across {len(list(PATHWAYS_DIR.glob('*.json')))} pathway files -> {OUT_PATH}")


if __name__ == "__main__":
    main()
