"""Turn the Phase 5/6/7 outputs into static JSON the app/ frontend fetches
directly (sankey.json, matrix.json, pathways/<in>__<out>.json, manifest.json)
with no backend/API server.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import polars as pl

from io_analysis import classification as classification_module
from io_analysis.aggregation import PROCESSING_LAYER_BY_ROLE, build_layer_graph
from io_analysis.classification import (
    MOTOR_SUBCLASS_TO_CATEGORY,
    MOTOR_SUPERCLASSES,
    SENSORY_SUPERCLASSES,
    build_classification,
)
from io_analysis.graph import DEFAULT_MAX_HOPS, INPUT_CATEGORIES, N_PAIRS_WITHIN_HOPS_COLUMN, OUTPUT_CATEGORIES, build_io_matrix, save_matrix
from io_analysis.load_data import EXPECTED_DATASET, PROJECT_ROOT, load_edges_manifest, load_nodes
from io_analysis.pathways import PATHWAYS_DIR, EmptyCategoryError, build_pathway_drilldown, load_graph_context, save_pathway_drilldown

APP_DATA_DIR = PROJECT_ROOT / "app" / "data"
PATHWAYS_OUT_DIR = APP_DATA_DIR / "pathways"
CLASSIFICATION_RULE_VERSION = "1.0.0"  # matches docs/io_classification_rules.md header
DEFAULT_PATHWAY_PARAMS = dict(max_hops=3, minimum_weight=1, top_n_paths=20, max_nodes=150)


def classification_rule_hash() -> str:
    """SHA-256 prefix of the complete classification.py source.

    Includes superclass lists, overrides and branch order as well as the
    mapping dictionaries. Comments also affect this source fingerprint;
    line endings are normalized so the same checkout hashes identically.
    """
    source = Path(classification_module.__file__).read_text(encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def write_json(path: Path, payload: dict, *, indent: int | None = None) -> None:
    """Reject NaN/infinity before touching an existing browser artifact."""
    encoded = json.dumps(payload, allow_nan=False, indent=indent)
    path.write_text(encoded, encoding="utf-8")

PROCESSING_LAYERS = list(PROCESSING_LAYER_BY_ROLE.values())


def export_sankey() -> dict:
    layer_graph = build_layer_graph()

    stage1 = layer_graph.filter(
        pl.col("source_layer").is_in(INPUT_CATEGORIES) & pl.col("target_layer").is_in(PROCESSING_LAYERS)
    )
    stage2 = layer_graph.filter(
        pl.col("source_layer").is_in(PROCESSING_LAYERS) & pl.col("target_layer").is_in(OUTPUT_CATEGORIES)
    )
    flows = pl.concat([stage1, stage2])

    nodes = sorted(set(flows["source_layer"].to_list()) | set(flows["target_layer"].to_list()))
    node_index = {name: i for i, name in enumerate(nodes)}

    def node_stage(name: str) -> str:
        if name in INPUT_CATEGORIES:
            return "input"
        if name in OUTPUT_CATEGORIES:
            return "output"
        return "processing"

    links = []
    for row in flows.iter_rows(named=True):
        links.append({
            "source": node_index[row["source_layer"]],
            "target": node_index[row["target_layer"]],
            "total_weight": row["total_weight"],
            # source-side count avoids double-counting fan-out on the target side
            "n_unique_neurons": row["n_unique_source_neurons"],
            "n_directed_connections": row["n_directed_connections"],
        })

    return {
        "nodes": [{"name": n, "stage": node_stage(n)} for n in nodes],
        "links": links,
        "metrics": ["total_weight", "n_unique_neurons", "n_directed_connections"],
    }


def export_matrix() -> dict:
    matrix = build_io_matrix()  # uses graph.DEFAULT_MAX_HOPS
    metrics = [
        "reachable", "shortest_path_hops", "weighted_shortest_path", N_PAIRS_WITHIN_HOPS_COLUMN, "max_flow",
        "max_flow_frac_of_input_output", "max_flow_frac_of_output_input",
    ]
    cells = matrix.to_dicts()
    payload = {
        "input_categories": INPUT_CATEGORIES,
        "output_categories": OUTPUT_CATEGORIES,
        "metrics": metrics,
        "n_pairs_within_hops_value": DEFAULT_MAX_HOPS,  # the actual hop bound behind N_PAIRS_WITHIN_HOPS_COLUMN
        "cells": cells,
    }
    # The downloadable CSV and browser JSON describe the same computation.
    # Validate JSON values before updating either artifact.
    json.dumps(payload, allow_nan=False)
    save_matrix(matrix)
    return payload


def export_pathways() -> list[str]:
    PATHWAYS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    graph, nodes_meta = load_graph_context()
    written = []
    for in_cat in INPUT_CATEGORIES:
        for out_cat in OUTPUT_CATEGORIES:
            try:
                tables = build_pathway_drilldown(
                    in_cat, out_cat, graph=graph, nodes_meta=nodes_meta, **DEFAULT_PATHWAY_PARAMS
                )
            except EmptyCategoryError:
                continue  # no neurons in one of the categories - skip (any other ValueError propagates)
            payload = {
                "input_category": in_cat,
                "output_category": out_cat,
                "params": DEFAULT_PATHWAY_PARAMS,
                "nodes": tables["nodes"].to_dicts(),
                "edges": tables["edges"].to_dicts(),
                "paths": tables["paths"].to_dicts(),
            }
            fname = f"{in_cat}__{out_cat}.json"
            write_json(PATHWAYS_OUT_DIR / fname, payload)
            # Refresh existing standalone examples from these exact tables,
            # rather than leaving old CSVs behind after a new app export.
            if (PATHWAYS_DIR / f"{in_cat}__{out_cat}").is_dir():
                save_pathway_drilldown(in_cat, out_cat, tables)
            written.append(fname)
    return written


def export_category_counts() -> dict:
    """Full-census counts per input_category/processing io_role/output_category,
    generated from classification.py's actual output so the app's category
    legend cannot drift from the classification after a rule change.
    """
    classification = build_classification(load_nodes())
    input_counts = {
        r["input_category"]: r["count"]
        for r in classification.filter(pl.col("input_category") != "not_input")["input_category"].value_counts().to_dicts()
    }
    output_counts = {
        r["output_category"]: r["count"]
        for r in classification.filter(pl.col("output_category") != "not_output")["output_category"].value_counts().to_dicts()
    }
    processing = classification.filter(pl.col("io_role").is_in(list(PROCESSING_LAYER_BY_ROLE.keys())))
    processing_counts = {
        r["layer"]: r["count"]
        for r in processing.with_columns(pl.col("io_role").replace(PROCESSING_LAYER_BY_ROLE).alias("layer"))["layer"]
        .value_counts().to_dicts()
    }
    return {
        "input": input_counts,
        "processing": processing_counts,
        "output": output_counts,
        "unknown": classification.filter(pl.col("io_role") == "unknown").height,
        "total_census": classification.height,
    }


def git_commit_hash() -> str | None:
    """Best-effort - None outside a git repo or before the first commit,
    not a hard failure (this project isn't always run from a git checkout).
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def git_worktree_dirty() -> bool | None:
    """Distinguish a build from local changes from one at the recorded HEAD."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def export_coverage() -> dict:
    """Uncertainty/coverage stats for the app's "Coverage & uncertainty"
    panel - the numbers this project has repeatedly had to re-derive by
    hand during review rounds (Traced/statusLabel breakdown, missing
    class/subclass, output_category's subclass-vs-exitNerve composition),
    computed once here instead of hand-copied into docs each time.
    """
    nodes = load_nodes()
    traced = nodes.filter(pl.col("status") == "Traced")
    status_label_counts = {
        r["statusLabel"]: r["count"]
        for r in traced["statusLabel"].value_counts().to_dicts() if r["statusLabel"] is not None
    }

    classification = build_classification(nodes)
    output_rows = classification.filter(pl.col("output_category") != "not_output")
    # Count successful assignments, not merely rows eligible for a branch:
    # xm and multi-nerve overrides deliberately leave some outputs unknown.
    resolved_outputs = output_rows.filter(pl.col("output_category") != "unknown").join(
        nodes.select("bodyid", "superclass", "subclass"), on="bodyid", how="inner"
    )
    output_subclass_derived = resolved_outputs.filter(
        pl.col("superclass").is_in(MOTOR_SUPERCLASSES)
        & pl.col("subclass").is_in(list(MOTOR_SUBCLASS_TO_CATEGORY))
    ).height
    output_total = output_rows.height
    output_unknown = output_total - resolved_outputs.height

    sensory_rows = nodes.filter(pl.col("superclass").is_in(SENSORY_SUPERCLASSES))

    return {
        "total_census": nodes.height,
        "traced": traced.height,
        "traced_status_label_counts": status_label_counts,
        "superclass_missing": nodes.filter(pl.col("superclass").is_null()).height,
        "superclass_tbc": nodes.filter(pl.col("superclass").str.ends_with("_tbc").fill_null(False)).height,
        "sensory_class_missing": sensory_rows.filter(pl.col("class").is_null()).height,
        "sensory_total": sensory_rows.height,
        "output_category_total": output_total,
        "output_category_subclass_derived": output_subclass_derived,
        "output_category_exit_nerve_fallback": resolved_outputs.height - output_subclass_derived,
        "output_category_unknown": output_unknown,
    }


def export_manifest(
    sankey: dict, matrix: dict, pathway_files: list[str], category_counts: dict, coverage: dict
) -> dict:
    edges_manifest = load_edges_manifest()
    nodes = load_nodes()
    manifest = {
        "dataset": EXPECTED_DATASET,
        "git_commit": git_commit_hash(),
        "git_dirty": git_worktree_dirty(),
        "edge_extraction_timestamp_utc": edges_manifest.get("extraction_timestamp_utc"),
        "app_export_timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "node_count_total_census": nodes.height,
        "node_count_traced": nodes.filter(pl.col("status") == "Traced").height,
        "edge_count": edges_manifest.get("row_count"),
        "classification_rule_version": CLASSIFICATION_RULE_VERSION,
        "classification_rule_hash": classification_rule_hash(),
        "classification_rule_hash_scope": "complete classification.py source (SHA-256 prefix)",
        "pathway_default_params": DEFAULT_PATHWAY_PARAMS,
        "sankey_stage_count": len(sankey["nodes"]),
        "sankey_link_count": len(sankey["links"]),
        "matrix_cell_count": len(matrix["cells"]),
        "pathway_pair_count": len(pathway_files),
        "coverage": coverage,
        "category_counts": category_counts,
        "note": "weighted_shortest_path and max_flow are topological/graph measures "
                "(cost=1/weight, capacity=weight) - not biological signal-strength claims.",
    }
    return manifest


def main() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Exporting Sankey data (View 1) ...")
    sankey = export_sankey()
    write_json(APP_DATA_DIR / "sankey.json", sankey)
    print(f"  {len(sankey['nodes'])} nodes, {len(sankey['links'])} links")

    print("Exporting matrix data (View 2) ...")
    matrix = export_matrix()
    write_json(APP_DATA_DIR / "matrix.json", matrix)
    print(f"  {len(matrix['cells'])} cells")

    print("Exporting pathway drill-downs (View 2 click-through / View 3) ...")
    t0 = time.time()
    pathway_files = export_pathways()
    print(f"  {len(pathway_files)} pairs in {time.time()-t0:.1f}s")

    print("Computing category counts (legend) ...")
    category_counts = export_category_counts()

    print("Computing coverage/uncertainty stats ...")
    coverage = export_coverage()

    manifest = export_manifest(sankey, matrix, pathway_files, category_counts, coverage)
    write_json(APP_DATA_DIR / "manifest.json", manifest, indent=2)
    print(f"\nSaved app data -> {APP_DATA_DIR}")


if __name__ == "__main__":
    main()
