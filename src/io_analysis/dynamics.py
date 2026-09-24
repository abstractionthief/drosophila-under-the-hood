"""Illustrative leaky-integrator simulation on the 24-layer aggregate graph
(not per-neuron - real time constants/delays/thresholds aren't available).
Weight = row-normalized total_weight; sign = majority NT class per layer,
a coarse simplification (see docs/domain_reference.md section 6).
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl

from io_analysis.aggregation import PROCESSING_LAYER_BY_ROLE, add_layer, build_layer_graph
from io_analysis.classification import build_classification
from io_analysis.graph import INPUT_CATEGORIES, OUTPUT_CATEGORIES
from io_analysis.load_data import PROJECT_ROOT, load_nodes

PROCESSING_LAYERS = set(PROCESSING_LAYER_BY_ROLE.values())


def stage_of(layer: str) -> str:
    if layer in INPUT_CATEGORIES:
        return "input"
    if layer in OUTPUT_CATEGORIES:
        return "output"
    if layer in PROCESSING_LAYERS:
        return "processing"
    return "unknown"

DYNAMICS_OUT_PATH = PROJECT_ROOT / "app" / "data" / "dynamics.json"

EXCITATORY_NT = {"acetylcholine", "glutamate", "dopamine", "octopamine"}
INHIBITORY_NT = {"gaba", "histamine"}


def layer_order(layer_graph: pl.DataFrame) -> list[str]:
    return sorted(set(layer_graph["source_layer"].to_list()) | set(layer_graph["target_layer"].to_list()))


def build_signed_weight_matrix() -> tuple[np.ndarray, list[str], dict[str, float]]:
    nodes = load_nodes()
    classification = build_classification(nodes)
    layered = add_layer(classification).select("bodyid", "layer")
    layer_graph = build_layer_graph()

    layers = layer_order(layer_graph)
    idx = {l: i for i, l in enumerate(layers)}
    n = len(layers)

    # sign per layer, from majority neurotransmitter of its neurons
    nt = nodes.select("bodyid", "consensusNt").join(layered, on="bodyid", how="inner")
    nt = nt.with_columns(pl.col("consensusNt").str.to_lowercase().alias("nt_lower"))

    # One sign per layer is a coarse majority vote over a mixed population -
    # in practice this collapses 23 of 24 layers to "excitatory" (only
    # `vision` comes out inhibitory), discarding real per-neuron inhibitory
    # diversity within every other layer. A known simplification, not a claim
    # that those layers are uniformly excitatory.
    sign_by_layer: dict[str, float] = {}
    for layer in layers:
        sub = nt.filter(pl.col("layer") == layer)
        n_exc = sub.filter(pl.col("nt_lower").is_in(list(EXCITATORY_NT))).height
        n_inh = sub.filter(pl.col("nt_lower").is_in(list(INHIBITORY_NT))).height
        if n_exc + n_inh == 0:
            sign_by_layer[layer] = 1.0  # no NT info at all - default excitatory, flagged in output
        else:
            sign_by_layer[layer] = -1.0 if n_inh > n_exc else 1.0

    # row-normalized signed weight matrix
    W = np.zeros((n, n))
    for row in layer_graph.iter_rows(named=True):
        i, j = idx[row["source_layer"]], idx[row["target_layer"]]
        W[i, j] = row["total_weight"]

    row_sums = W.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    W_norm = W / row_sums
    for layer, i in idx.items():
        W_norm[i, :] *= sign_by_layer[layer]

    return W_norm, layers, sign_by_layer


def simulate(
    W: np.ndarray,
    layers: list[str],
    stimulus_layer: str,
    stimulus_amplitude: float = 3.0,
    stimulus_duration: int = 5,
    n_steps: int = 150,
    dt: float = 0.5,
    tau: float = 3.0,
    gain: float = 0.3,
) -> np.ndarray:
    """Euler-integrate dx/dt = -x/tau + tanh(gain * W^T @ x + input(t)).
    Returns array of shape (n_steps, n_layers).
    """
    n = len(layers)
    x = np.zeros(n)
    stim_idx = layers.index(stimulus_layer)
    trace = np.zeros((n_steps, n))
    for t in range(n_steps):
        inp = np.zeros(n)
        if t < stimulus_duration:
            inp[stim_idx] = stimulus_amplitude
        dx = -x / tau + np.tanh(gain * (W.T @ x) + inp)
        x = x + dt * dx
        trace[t] = x
    return trace


def main() -> None:
    W, layers, sign_by_layer = build_signed_weight_matrix()

    print("Layer signs (majority neurotransmitter class):")
    for l in layers:
        print(f"  {l:22s} {'excitatory' if sign_by_layer[l] > 0 else 'inhibitory'}")

    stimulus_layers = ["olfaction", "vision", "mechanosensation"]
    missing_stimuli = [s for s in stimulus_layers if s not in layers]
    if missing_stimuli:
        print(f"WARNING: skipping stimulus layer(s) absent from this run's layer graph: {missing_stimuli}")
    stimulus_layers = [s for s in stimulus_layers if s in layers]

    runs = {}
    for stim in stimulus_layers:
        trace = simulate(W, layers, stimulus_layer=stim)
        runs[stim] = trace.tolist()
        peak_layer = layers[int(np.argmax(np.abs(trace).max(axis=0)))]
        print(f"Stimulus={stim}: peak overall activity in layer '{peak_layer}'")

    payload = {
        "layers": layers,
        "layer_stage": {l: stage_of(l) for l in layers},
        "layer_sign": sign_by_layer,
        "params": {"dt": 0.5, "tau": 3.0, "gain": 0.3, "stimulus_amplitude": 3.0, "stimulus_duration": 5, "n_steps": 150},
        "runs": runs,
        "caveat": (
            "Illustrative behavior of this specific toy model, not a validated physiological "
            "simulation - not even qualitatively (ordering/timing unverified). Weights are "
            "row-normalized total synapse counts (topological). Sign is majority-neurotransmitter-"
            "class per layer, a coarse simplification that collapses 23 of this run's 24 layers to "
            "\"excitatory\" (only `vision` comes out inhibitory) - it discards real per-neuron "
            "inhibitory diversity within every other layer, and glutamate/dopamine/octopamine are "
            "grouped as excitatory by convention despite receptor-dependent real signs. Time units "
            "(dt/tau) are simulation units, not measured biological time constants. The default "
            "gain=0.3 sits just below this specific weight matrix's own linear stability threshold "
            "(~0.334 for tau=3, derived from its largest eigenvalue) - that threshold is a direct "
            "mathematical consequence of this normalization/tau choice, not a discovered property "
            "of the connectome. See src/io_analysis/dynamics.py and docs/domain_reference.md."
        ),
    }
    DYNAMICS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DYNAMICS_OUT_PATH.write_text(json.dumps(payload))
    print(f"\nSaved -> {DYNAMICS_OUT_PATH}")


if __name__ == "__main__":
    main()
