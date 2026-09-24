"""Export per-neuron skeleton geometry (from neuron_skeletons.parquet) for
Neuron Detail. Neurons above MAX_POINTS are decimated, keeping branch/leaf/
root/soma points and reconnecting each kept point to its nearest kept
ancestor - a naive "keep only direct parent" version left disconnected dust.
"""

from __future__ import annotations

import json
import math

import polars as pl

from io_analysis.load_data import PROJECT_ROOT

SKELETONS_PATH = PROJECT_ROOT / "data" / "raw" / "neuron_skeletons.parquet"
OUT_DIR = PROJECT_ROOT / "app" / "data" / "skeletons"
MAX_POINTS = 800


def _nearest_kept_factory(parent_of: dict[int, int], keep_set: set[int]):
    cache: dict[int, int] = {}

    def nearest_kept(pid: int) -> int:
        path = []
        cur = pid
        while True:
            if cur == -1:
                result = -1
                break
            if cur in cache:
                result = cache[cur]
                break
            if cur in keep_set:
                result = cur
                break
            path.append(cur)
            cur = parent_of.get(cur, -1)
        for node in path:
            cache[node] = result
        return result

    return nearest_kept


def export_one(bodyid: int, d: pl.DataFrame) -> dict:
    n_original = d.height
    rows = {r["PointNo"]: r for r in d.iter_rows(named=True)}
    parent_of = {pid: r["Parent"] for pid, r in rows.items()}

    child_count: dict[int, int] = {}
    for r in rows.values():
        if r["Parent"] != -1:
            child_count[r["Parent"]] = child_count.get(r["Parent"], 0) + 1

    def is_important(pid: int) -> bool:
        r = rows[pid]
        return r["Parent"] == -1 or child_count.get(pid, 0) == 0 or child_count.get(pid, 0) >= 2 or r["is_soma"]

    decimated = n_original > MAX_POINTS
    if decimated:
        important_ids = [pid for pid in rows if is_important(pid)]
        important_set = set(important_ids)
        chain_ids = [pid for pid in rows if pid not in important_set]
        n_always = len(important_ids)
        target_chain_keep = max(0, MAX_POINTS - n_always)
        stride = max(1, math.ceil(len(chain_ids) / target_chain_keep)) if target_chain_keep > 0 else len(chain_ids) + 1
        keep_set = set(important_ids) | set(chain_ids[::stride])
    else:
        keep_set = set(rows.keys())

    soma = None
    soma_ids = [pid for pid, r in rows.items() if r["is_soma"]]
    if soma_ids:
        s = rows[soma_ids[0]]
        soma = {"x": round(s["X"]), "y": round(s["Y"]), "z": round(s["Z"])}

    nearest_kept = _nearest_kept_factory(parent_of, keep_set)
    x, y, z = [], [], []
    for pid in keep_set:
        eff_parent = nearest_kept(parent_of.get(pid, -1))
        if eff_parent == -1 or eff_parent == pid:
            continue
        p, pa = rows[pid], rows[eff_parent]
        # rounded to the nearest nm: sub-nanometer precision is below the
        # EM volume's own voxel resolution and pure JSON-size overhead here
        x.extend([round(p["X"]), round(pa["X"]), None])
        y.extend([round(p["Y"]), round(pa["Y"]), None])
        z.extend([round(p["Z"]), round(pa["Z"]), None])

    return {
        "bodyid": bodyid,
        "n_points_original": n_original,
        "n_points_exported": len(keep_set),
        "decimated": decimated,
        "units": "nm",
        "soma": soma,
        "x": x,
        "y": y,
        "z": z,
    }


def main() -> None:
    if not SKELETONS_PATH.exists():
        raise FileNotFoundError(f"{SKELETONS_PATH} not found - run r/build_neuron_skeletons.R first.")

    skeletons = pl.read_parquet(SKELETONS_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # partition_by groups the whole frame in one pass; a per-bodyid
    # .filter() in a loop re-scans all 14M+ rows once per neuron (~14x
    # slower, measured) for the same result.
    by_neuron = skeletons.partition_by("bodyid", as_dict=True)
    manifest_ids = []
    for (bodyid,), d in sorted(by_neuron.items()):
        record = export_one(bodyid, d)
        (OUT_DIR / f"{bodyid}.json").write_text(json.dumps(record))
        manifest_ids.append(bodyid)

    (OUT_DIR / "manifest.json").write_text(json.dumps({"bodyids": manifest_ids, "max_points": MAX_POINTS}))
    print(f"Exported {len(manifest_ids)} neuron skeletons -> {OUT_DIR}")


if __name__ == "__main__":
    main()
