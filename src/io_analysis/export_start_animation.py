"""Export the Start Here animation: a sample of real neurons at their soma
positions, each with the traversal layer at which a wave from one sensory
modality reaches it.

Run: uv run python -m io_analysis.export_start_animation
Output: app/data/start_animation.json (deterministic for identical inputs).

Layers come from the same deterministic input-fraction traversal as the
Wiring to Computation statistics (primer_stats.traversal_layers), seeded with one modality's
sensory neurons at a time. They order neurons by anatomical input, not by
measured activity or physiological time.
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import scipy.sparse as sp

from io_analysis.classification import build_classification
from io_analysis.export_positions import POSITIONS_PATH
from io_analysis.load_data import PROJECT_ROOT, load_edges, load_edges_manifest, load_nodes
from io_analysis.primer_stats import traversal_layers

OUT_PATH = PROJECT_ROOT / "app" / "data" / "start_animation.json"
THRESHOLD_PERCENT = 10
WAVES = [
    ("vision", "Vision"),
    ("olfaction", "Smell"),
    ("mechanosensation", "Touch"),
    ("gustation", "Taste"),
    ("proprioception", "Body position"),
]
# Per-role cap on the sample; small but behaviourally central populations
# get more than their census share so they stay visible. sensory_input is
# a cap, not a guarantee: only receptors with a mapped soma can be drawn.
ROLE_QUOTA = {
    "optic_processing": 820,
    "central_processing": 420,
    "vnc_processing": 230,
    "sensory_input": 260,
    "descending": 70,
    "ascending": 60,
    "motor_output": 70,
    "endocrine_output": 15,
    "other_efferent": 15,
}
ROLE_ORDER = list(ROLE_QUOTA)
# Giant Fiber (DNp01), left and right: always included as the named accent.
ACCENT_BODYIDS = (10001, 10010)
COORD_SCALE = 1000
SEED = 0


def sample_indices(roles: np.ndarray, categories: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Per-role quota; sensory neurons split evenly across the waves' modalities."""
    chosen = []
    for role, quota in ROLE_QUOTA.items():
        if role == "sensory_input":
            per_modality = quota // len(WAVES)
            for modality, _ in WAVES:
                pool = np.flatnonzero((roles == role) & (categories == modality))
                chosen.append(rng.choice(pool, size=min(per_modality, pool.size), replace=False))
            continue
        pool = np.flatnonzero(roles == role)
        chosen.append(rng.choice(pool, size=min(quota, pool.size), replace=False))
    return np.sort(np.concatenate(chosen))


def normalize_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Equal-scale X-Y projection onto [0, COORD_SCALE] along the wider axis,
    clipped to the 0.5-99.5% range so stray somas don't shrink the fly."""
    x_lo, x_hi = np.percentile(x, [0.5, 99.5])
    y_lo, y_hi = np.percentile(y, [0.5, 99.5])
    span = max(x_hi - x_lo, y_hi - y_lo)
    nx = np.clip((x - x_lo) / span, 0, (x_hi - x_lo) / span)
    ny = np.clip((y - y_lo) / span, 0, (y_hi - y_lo) / span)
    aspect = float((x_hi - x_lo) / (y_hi - y_lo))
    return np.rint(nx * COORD_SCALE).astype(int), np.rint(ny * COORD_SCALE).astype(int), aspect


def build() -> dict:
    nodes = load_nodes().filter(pl.col("status") == "Traced").sort("bodyid")
    classified = build_classification(nodes).sort("bodyid")
    ids = nodes["bodyid"].to_numpy()
    roles = classified["io_role"].to_numpy()
    categories = classified["input_category"].to_numpy()

    edges = load_edges()
    src = np.searchsorted(ids, edges["source"].to_numpy())
    dst = np.searchsorted(ids, edges["target"].to_numpy())
    for indices, column in ((src, "source"), (dst, "target")):
        if np.any(indices >= ids.size) or not np.array_equal(ids[indices], edges[column].to_numpy()):
            raise ValueError("An edge endpoint is not a Traced neuron in the current census.")
    incoming = sp.csr_matrix((edges["weight"].to_numpy().astype(np.int64), (dst, src)), shape=(ids.size, ids.size))
    del edges, src, dst

    positions = pl.read_csv(POSITIONS_PATH).with_columns(pl.col("bodyid").cast(pl.Int64))
    has_pos = np.isin(ids, positions["bodyid"].to_numpy())
    rng = np.random.default_rng(SEED)
    sample = sample_indices(np.where(has_pos, roles, "no_position"), categories, rng)
    accent = np.flatnonzero(np.isin(ids, ACCENT_BODYIDS) & has_pos)
    sample = np.union1d(sample, accent)

    pos = pl.DataFrame({"bodyid": ids[sample]}).join(positions, on="bodyid", how="left")
    x, y, aspect = normalize_xy(pos["x"].to_numpy().astype(float), pos["y"].to_numpy().astype(float))

    waves = []
    for modality, label in WAVES:
        seeds = (roles == "sensory_input") & (categories == modality)
        layers = traversal_layers(incoming, seeds, THRESHOLD_PERCENT)
        waves.append({
            "modality": modality, "label": label,
            "seed_count": int(seeds.sum()),
            # Most receptor somas lie outside the positioned CNS, so this is
            # often 0: the app then says the wave appears at the first targets.
            "sampled_seed_count": int(seeds[sample].sum()),
            "max_layer": int(layers.max()),
            "layer": layers[sample].tolist(),
        })

    manifest = load_edges_manifest()
    return {
        "schema_version": 1,
        "dataset": manifest["dataset"],
        "n": int(sample.size),
        "bodyid": ids[sample].tolist(),
        "x": x.tolist(), "y": y.tolist(), "aspect": aspect,
        "role_names": ROLE_ORDER,
        "role": [ROLE_ORDER.index(r) for r in roles[sample]],
        "accent_bodyids": [int(b) for b in ids[accent]],
        "threshold_percent": THRESHOLD_PERCENT,
        "waves": waves,
        "note": (
            f"Deterministic sample of {sample.size} traced neurons with a soma position, "
            "projected from measured X-Y coordinates, with each axis clipped to the sample's "
            "0.5–99.5 percentile range and rounded for display. Each wave orders neurons by an input-fraction "
            f"traversal from one sensory modality (a neuron joins once earlier layers supply "
            f">= {THRESHOLD_PERCENT}% of its input synapses). This ordering is anatomical, not "
            "recorded activity or physiological timing."
        ),
    }


def main() -> None:
    payload = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    print(f"Exported {payload['n']} neurons x {len(payload['waves'])} waves -> {OUT_PATH.relative_to(PROJECT_ROOT)}")
    for w in payload["waves"]:
        layers = np.array(w["layer"])
        print(f"  {w['label']:<14} seeds {w['seed_count']:>5} (sampled {w['sampled_seed_count']:>3})  "
              f"max layer {w['max_layer']:>2}  sampled unreached {(layers < 0).sum()}")


if __name__ == "__main__":
    main()
