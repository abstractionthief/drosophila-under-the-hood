"""Reproduce the Wiring to Computation view's descriptive statistics, without a dynamics model.

Run: .venv/bin/python -m io_analysis.primer_stats
Output: data/ml_primer_stats.json (deterministic for identical inputs/code/env).
Uses the full Traced chemical-synapse graph, including weight-1 edges. No
connectivity or classification input is modified. Traversal layers describe a
specified graph algorithm, not physiological time or neural-network depth.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import polars as pl
import scipy
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

from io_analysis import classification, load_data
from io_analysis.classification import build_classification
from io_analysis.load_data import PROJECT_ROOT, load_edges, load_edges_manifest, load_nodes

OUTPUT_PATH = PROJECT_ROOT / "data" / "ml_primer_stats.json"


def fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def fraction(count: int, total: int) -> dict:
    return {"count": int(count), "denominator": int(total),
            "fraction": float(count / total) if total else None}


def median(values: np.ndarray) -> float | None:
    return float(np.median(values)) if values.size else None


def population_layers(layers: np.ndarray, population: np.ndarray) -> dict:
    selected = layers[population]
    reached = selected[selected >= 0]
    return {
        "population_count": int(selected.size),
        "reached_count": int(reached.size),
        "unreached_count": int(selected.size - reached.size),
        "median_layer_among_reached": median(reached),
        "deepest_reached_layer": int(reached.max()) if reached.size else None,
    }


def traversal_layers(incoming: sp.csr_matrix, seeds: np.ndarray, threshold_percent: int) -> np.ndarray:
    """Synchronous monotone closure; each new layer sees all *earlier* layers.

    Integer cross-multiplication avoids rounding at the input-fraction boundary.
    Seeds enter at layer 0 regardless of their input; non-seeds without input
    remain unreached (-1). There is no iteration cap: stop at the fixed point.
    """
    totals = np.asarray(incoming.sum(axis=1)).ravel().astype(np.int64)
    layers = np.full(seeds.size, -1, dtype=np.int32)
    layers[seeds] = 0
    step = 0
    while True:
        reached = layers >= 0
        from_reached = incoming @ reached.astype(np.int64)
        join = (~reached) & (totals > 0) & (100 * from_reached >= threshold_percent * totals)
        if not join.any():
            break
        step += 1
        layers[join] = step
    return layers


def traversal(incoming: sp.csr_matrix, seeds: np.ndarray, roles: np.ndarray,
              threshold_percent: int) -> dict:
    layers = traversal_layers(incoming, seeds, threshold_percent)
    return {
        "threshold_percent": threshold_percent,
        "all_neurons_including_seeds": population_layers(layers, np.ones(seeds.size, dtype=bool)),
        "nonseed_neurons": population_layers(layers, ~seeds),
        "descending_neurons": population_layers(layers, roles == "descending"),
        "motor_neurons": population_layers(layers, roles == "motor_output"),
        "layer_counts_including_seeds": np.bincount(layers[layers >= 0]).tolist(),
    }


def summarize() -> dict:
    print("Loading and validating source data...", flush=True)
    nodes = load_nodes().filter(pl.col("status") == "Traced").sort("bodyid")
    classified = build_classification(nodes).sort("bodyid")
    ids = nodes["bodyid"].to_numpy()
    roles = classified["io_role"].to_numpy()
    edges = load_edges()
    src = np.searchsorted(ids, edges["source"].to_numpy()).astype(np.int32)
    dst = np.searchsorted(ids, edges["target"].to_numpy()).astype(np.int32)
    for indices, column in ((src, "source"), (dst, "target")):
        if np.any(indices >= ids.size) or not np.array_equal(ids[indices], edges[column].to_numpy()):
            raise ValueError("An edge endpoint is not a Traced neuron in the current census.")
    weights = edges["weight"].to_numpy().astype(np.int32)
    n, n_edges = ids.size, weights.size
    total_weight = int(weights.sum(dtype=np.int64))
    seeds = roles == "sensory_input"
    sensory_unknown = seeds & (classified["input_category"].to_numpy() == "unknown")
    self_loops = src == dst

    thresholds = []
    for minimum in (5, 10):
        mask = weights >= minimum
        thresholds.append({
            "minimum_synapses": minimum,
            "edges": fraction(int(mask.sum()), n_edges),
            "synapses": fraction(int(weights[mask].sum(dtype=np.int64)), total_weight),
        })
    weighted_sources = np.bincount(src, weights=weights, minlength=n).astype(np.int64)
    nt_values = nodes["consensusNt"].fill_null("missing").to_numpy()
    nt_shares = {
        nt: fraction(int(weighted_sources[nt_values == nt].sum()), total_weight)
        for nt in sorted(set(nt_values))
    }
    input_shares = {}
    for target_role in ("descending", "motor_output"):
        selected = roles[dst] == target_role
        by_source = np.bincount(src[selected], weights=weights[selected], minlength=n).astype(np.int64)
        denominator = int(by_source.sum())
        input_shares[target_role] = {
            "target_neuron_count": int((roles == target_role).sum()),
            "input_synapse_count": denominator,
            "source_io_role": {
                role: fraction(int(by_source[roles == role].sum()), denominator)
                for role in sorted(set(roles))
            },
        }

    classes = nodes["class"].to_numpy()
    pns, kcs = classes == "ALPN", classes == "Kenyon_Cell"
    pn_kc = pns[src] & kcs[dst]
    kc_degree = np.bincount(dst[pn_kc], minlength=n)[kcs]
    pn_kc_summary = {
        "projection_neuron_class": "ALPN", "kenyon_cell_class": "Kenyon_Cell",
        "all_projection_neuron_count": int(pns.sum()), "all_kenyon_cell_count": int(kcs.sum()),
        "connected_projection_neuron_count": int(np.unique(src[pn_kc]).size),
        "connected_kenyon_cell_count": int((kc_degree > 0).sum()),
        "kenyon_cells_without_recorded_alpn_input": int((kc_degree == 0).sum()),
        "directed_edge_count": int(pn_kc.sum()),
        "median_alpn_partners_all_kenyon_cells_including_zeros": median(kc_degree),
        "median_alpn_partners_connected_kenyon_cells": median(kc_degree[kc_degree > 0]),
    }
    degrees = {}
    for label, indices in (("incoming", dst), ("outgoing", src)):
        counts = np.bincount(indices, minlength=n)
        degrees[label] = {"median": median(counts), "p99": float(np.percentile(counts, 99)),
                          "maximum": int(counts.max()), "zero_degree_count": int((counts == 0).sum())}
    typed = nodes.filter(pl.col("type").is_not_null()).group_by("type").len()
    descriptive = {
        "traced_neuron_count": int(n), "directed_edge_count": int(n_edges),
        "synapse_count": total_weight, "self_loop_edge_count": int(self_loops.sum()),
        "density_including_self_pairs": fraction(n_edges, n * n),
        "edge_weight": {"median": float(np.median(weights)), "mean": total_weight / n_edges,
                        "maximum": int(weights.max())},
        "edge_thresholds": thresholds, "partner_degree_including_zero_degree_and_self_loops": degrees,
        "nonmissing_type_count": typed.height, "median_neurons_per_nonmissing_type": float(typed["len"].median()),
        "neurons_without_type": int(nodes["type"].null_count()),
        "consensus_neurotransmitter_source_synapse_shares": nt_shares,
        "input_synapse_shares_by_io_role": input_shares, "alpn_to_kenyon_cells": pn_kc_summary,
    }
    # Incoming CSR lets each sparse matvec sum the current sources of every
    # target. Reversing all edges leaves strongly connected components intact.
    print("Building sparse incoming matrix...", flush=True)
    incoming = sp.csr_matrix((weights, (dst, src)), shape=(n, n))
    del edges, src, dst, weights, self_loops, pn_kc
    print("Computing SCC and reciprocal-edge counts...", flush=True)
    component_count, component = connected_components(incoming, directed=True, connection="strong")
    largest = int(np.bincount(component).max())
    binary = incoming.astype(bool)
    mutual = binary.multiply(binary.T)
    # Exclude autapses from both reciprocity numerator and denominator.
    reciprocal = mutual.nnz - int(np.count_nonzero(mutual.diagonal()))
    descriptive["strong_components"] = {
        "component_count": int(component_count), "largest": fraction(largest, n),
    }
    descriptive["reciprocal_nonself_directed_edges"] = fraction(
        reciprocal, n_edges - descriptive["self_loop_edge_count"])
    del binary, mutual, component

    direct = (incoming @ seeds.astype(np.int64)) > 0
    within_one = seeds | direct
    within_two = within_one | ((incoming @ within_one.astype(np.int64)) > 0)
    motor = roles == "motor_output"
    descriptive["sensory_shortest_paths"] = {
        "within_two_hops_including_seed_neurons": fraction(int(within_two.sum()), n),
        "nonseed_neurons_within_two_hops": fraction(int((within_two & ~seeds).sum()), int((~seeds).sum())),
        "motor_neurons_with_direct_sensory_edge": fraction(int((motor & direct).sum()), int(motor.sum())),
    }
    print("Computing cumulative input-fraction traversals...", flush=True)
    traversals = [traversal(incoming, seeds, roles, threshold) for threshold in (10, 20, 30)]
    return {
        "schema_version": 1,
        "provenance": {
            "command": ".venv/bin/python -m io_analysis.primer_stats",
            "dataset": load_edges_manifest()["dataset"],
            "edge_extraction_timestamp_utc": load_edges_manifest()["extraction_timestamp_utc"],
            "files": [fingerprint(path) for path in (
                load_data.NODES_PATH, load_data.EDGES_PATH, load_data.EDGES_MANIFEST_PATH,
                Path(classification.__file__), Path(load_data.__file__), Path(__file__),
            )],
            "environment": {"python": platform.python_version(), "numpy": np.__version__,
                            "polars": pl.__version__, "scipy": scipy.__version__},
        },
        "definitions": {
            "population": "All and only census rows with status == Traced, including isolated neurons.",
            "edges": "Unique directed Traced-to-Traced chemical connections with weight >= 1; weight is reported synapse count. Autapses retained unless a metric explicitly excludes them.",
            "classification": "Current build_classification(nodes); DN means io_role == descending; motor means motor_output (includes cb_motor and vnc_motor).",
            "nt_shares": "Sum of outgoing synapse counts by source consensusNt, divided by all synapse counts; these are NT-label shares, not measured excitation/inhibition.",
            "input_shares": "Source io_role synapse counts onto every target in the stated target io_role, divided by all recorded input synapses to that target population. No roles omitted.",
            "reciprocity": "Fraction of nonself directed edges whose reverse edge is present; a reciprocal pair contributes two directed edges.",
            "type_count": "Unique non-null raw type annotations, not an independently validated biological type taxonomy.",
            "traversal": "Seeds are layer 0. Synchronously add each previously unreached neuron when cumulative synapse count from all earlier layers / total recorded input synapse count >= threshold. Iterate to fixed point; zero-input nonseeds remain unreached. This deterministic closure is not a physiological simulation or the stochastic traversal in Schlegel et al. 2021.",
            "traversal_medians": "Main population is nonseed_neurons: exclude sensory seeds, and calculate median only among reached neurons. Report unreached counts separately. Role medians likewise use reached members of that role. Layers are algorithmic, not measured processing depth/time.",
            "descending_ratio": "No brain-neuron/DN ratio reported: a count ratio would not establish bandwidth, exclusive routing through DN, or a functional bottleneck.",
        },
        "statistics": descriptive,
        "traversal_seed_population": {
            "io_role": "sensory_input", "count": int(seeds.sum()),
            "unknown_input_category_included": int(sensory_unknown.sum()),
        },
        "input_fraction_traversal": traversals,
    }


def main() -> None:
    result = summarize()
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"Saved {OUTPUT_PATH.relative_to(PROJECT_ROOT)}", flush=True)
    for row in result["input_fraction_traversal"]:
        print(f"{row['threshold_percent']}%: {row['nonseed_neurons']}", flush=True)


if __name__ == "__main__":
    main()
