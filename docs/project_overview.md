# connectome-lab: project overview (A to Z)

What this project is, how the pipeline is built, and — the biological
question — how information actually flows through the MaleCNS connectome.

## 1. What this project is

An exploration of the Janelia **male *Drosophila* CNS connectome**
(`male-cns:v1.0` via neuPrint), built bottom-up:

```
R / malecns  ->  data extraction  ->  normalized local tables
            ->  Python analysis  ->  interactive local visualization
```

The guiding question: *"What kinds of information enter the MaleCNS, how
are they routed through the nervous system, and what kinds of outputs
leave the CNS?"* Every classification rule below is derived from the
dataset's own fields (not string-matched cell names) and documented with
its confidence level and fallback (see `docs/io_classification_rules.md`);
"unknown" is used wherever the data doesn't support a confident label. Some
rules - notably the exitNerve-based fallback in `output_category` - are
still medium/low confidence, not certainty; read the confidence column
before treating any single row as authoritative.

## 2. The pipeline, end to end

| Stage | Script | What it does | Output |
|---|---|---|---|
| Smoke test | `r/smoke_test.R` | Verifies neuPrint auth + connectivity | console only |
| Single-neuron exploration | `r/inspect_neuron.R` | Inspects one neuron's metadata + connectivity API shape | console only |
| Seed circuit | `r/build_seed_circuit.R` | 1-hop neighborhood of a single neuron (10039, `VL2a_adPN_R`) | `data/seed_10039_*.csv` |
| **Census** | `r/build_io_census.R` | Full metadata for every DVID-annotated body (211,579 rows, 165,122 `Traced`) | `data/io_census_nodes.csv`, `results/io_census_report.txt` |
| **Connectivity** | `r/build_io_connectivity.R` | Every Traced->Traced synaptic connection, no threshold | `data/raw/io_edges.parquet` (25,563,197 edges) |
| **Classification** | `src/io_analysis/classification.py` | Derives `io_role` / `input_category` / `output_category` from raw fields, per documented rules | `data/io_classification.parquet` |
| **Layer aggregation** | `src/io_analysis/aggregation.py` | Collapses the whole graph to 24 coarse layers, 4 independent metrics | `data/io_layer_graph.csv` |
| **I/O matrix** | `src/io_analysis/graph.py` | Whole-connectome reachability/shortest-path/max-flow between 8 input x 10 output categories | `data/io_matrix.csv` |
| **Pathway drill-down** | `src/io_analysis/pathways.py` | Reduced, hop-bounded subgraph + ranked paths for one category pair | `data/pathways/<in>__<out>/*.csv` |
| **App data export** | `src/io_analysis/export_app_data.py` | Precomputes Sankey/matrix/all 80 drill-downs as static JSON | `app/data/*.json` |
| **Dynamics** | `src/io_analysis/dynamics.py` | Illustrative leaky-integrator simulation on the 24-layer aggregate graph | `app/data/dynamics.json` |
| **Positions** | `src/io_analysis/export_positions.py` | Soma position + io_role for the 140,024 of 165,122 traced neurons with recorded positions, for the Anatomy views | `app/data/positions.json` |
| **Skeletons** | `r/build_neuron_skeletons.R`, `export_skeletons.py` | Per-neuron 3D morphology for every bodyid reachable via a pathway drill-down | `app/data/skeletons/*.json` |
| **Search index** | `src/io_analysis/export_search_index.py` | Full-census (165k neuron) search index for the app's global search | `app/data/search_index.json` |
| **Visualization** | `app/index.html` + `app.js` | 9-view interactive explorer, static, no backend | browser |

Raw data (`data/io_census_nodes.csv`, `data/raw/io_edges.parquet`) is
never modified by later stages - every derived table is a separate file,
joined back by `bodyid`.

## 3. How the network is organized (the classification layer)

Every neuron gets one `io_role`, derived **only** from `superclass`
(the one field with near-complete coverage):

| io_role | meaning | count (of 211,579) |
|---|---|---|
| `optic_processing` | intrinsic optic-lobe / visual relay processing | 99,167 |
| `unknown` | no superclass, or dataset's own "_tbc" uncertainty marker | 45,023 |
| `central_processing` | intrinsic central-brain processing | 32,164 |
| `sensory_input` | primary sensory transduction (any modality) | 17,885 |
| `vnc_processing` | intrinsic ventral-nerve-cord processing | 13,161 |
| `ascending` | VNC -> brain relay | 1,846 |
| `descending` | brain -> VNC relay (command neurons) | 1,314 |
| `motor_output` | motor neurons | 815 |
| `other_efferent` | non-motor efferent | 110 |
| `endocrine_output` | neurosecretory output | 94 |

These counts are over the **full census** (`status` unfiltered), not just
`Traced` neurons - `sensory_input` drops to 15,896 and `visual` specifically
to 4,107 once restricted to `Traced` only, which is what the connectivity
graph (edges, Sankey, matrix, pathways) actually analyzes.

**`sensory_input`** neurons additionally get an `input_category`
(vision/olfaction/gustation/mechanosensation/proprioception/
hygrosensation/thermosensation/other_sensory), derived from `class` -
well-populated and high-confidence for this group.

**Output-role** neurons additionally get an `output_category`
(front_leg/middle_leg/hind_leg/wing/haltere/neck/proboscis/abdomen/
endocrine/other_motor). `class` is **100% missing** for these rows, so
unlike `input_category` this can't come from `class` at all. For motor
neurons (most of this group), it comes from their own documented
`subclass` label (MANC's motor-target nomenclature, high confidence);
`exitNerve` (external MANC nerve nomenclature, lower confidence) is only
a fallback for non-motor efferent/endocrine rows and the handful of motor
rows whose `subclass` doesn't resolve - see `docs/io_classification_rules.md`
section 3 for the exact priority and why the earlier `exitNerve`-only
version was wrong.

## 4. How the network is "orchestrated" - the actual flow

**The Overview Sankey (`app/`, View 1) is a selected I/O connectivity
summary, not the whole graph.** It shows only input->processing and
processing->output layer-to-layer links; it excludes processing<->processing
edges, recurrence, direct input->output edges, and links touching the
`unknown` layer. Measured from the actual exports: the full aggregated
layer graph has 311 layer-pair links summing 124,025,046 synapses; the
Sankey shows 67 of those links, summing 8,130,912 - **6.6% of total
synapse weight**. Read it as one slice through the connectome, not a
complete picture of signal flow.

Reading the Sankey left to right, **inputs** (8 modalities) feed into
**5 coarse processing regions**:

- `optic_lobe` (99,167 neurons - **the single largest population in the
  whole connectome**, ~47% of all DVID-annotated bodies) does the bulk of
  visual pre-processing before anything reaches the central brain.
- `central_brain` (32,164) is the main integration hub - olfaction,
  gustation, and relayed visual signal converge here.
- `vnc` (13,161) does local body/limb processing without brain
  involvement at all.
- `ascending` (1,846) and `descending` (1,314) are the two "highways"
  connecting brain and body - proprioceptive/sensory feedback goes up,
  motor commands go down. The classic example found in this project:
  **`DNp01`, the Giant Fiber** (bodyid 10001), a descending neuron.

**Outputs** (10 body-part categories, 1,019 neurons: 815 motor + 94
endocrine + 110 other efferent): Phase 6's matrix finds **all 80 input x
output category pairs reachable**, mostly within 1-2 hops. That means at
least one directed path exists between at least one neuron in each pair -
it says nothing about how many neurons participate, how strong the route
is, or whether it reflects typical signal routing rather than a rare
edge case. This connectome is recurrent (not a simple feedforward pipe),
but "reachable" here is a graph-existence claim, not a routing-strength one.

A concrete, traced example (Phase 7 drill-down, `olfaction -> front_leg`):
`ORN_VA3` -> `VA3_adPN` (projection neuron) -> `DNb05` (descending neuron)
-> `Sternotrochanter MN` (front-leg motor neuron). This is the first path
in the current export: body IDs `519971 -> 519970 -> 10065 -> 801079`,
3 hops, summed edge weight 126. Its minimum edge synapse count
(what the app calls "bottleneck weight") is 30 - a topological measure
of where that specific path is thinnest, not a physiological signal
strength, and single-contact (weight-1) edges are retained without a
threshold, so short-path results deserve a threshold-sensitivity check
before being read biologically.

**Important interpretive caveat** (carried through every analysis
script and the app's UI): synapse count is a topological/connectomic
measure here, never treated as a direct proxy for physiological signal
strength. "Weighted shortest path" uses cost=1/weight and "max-flow" uses
weight-as-capacity as graph-theoretic conventions, not biological claims.
Raw max-flow values in particular scale with category population size and
available synapse capacity - they measure topological redundancy between
the two selected neuron pools, not a normalized "functional coupling"
between input and output modalities, and aren't comparable across category
pairs with very different neuron counts without normalizing first.

## 5. Data-quality findings worth remembering

- The commonly-cited "~166k neurons" figure matches `status == "Traced"`
  (165,122), not the raw census row count (211,579). The rest breaks down
  as `Orphan` (15,925), `Glia` (11,864), `Unimportant` (10,751), no status
  at all (5,474), `Assign` (1,832), `Anchor` (611) - not uniformly
  "glia/orphan/fragment".
- **`Traced` is an operational reconstruction-pipeline filter, not a
  uniform completeness guarantee.** Among Traced rows, `statusLabel` is
  `Roughly traced` for 71,979 and `Prelim Roughly traced` for another
  36,387 - together roughly two-thirds of all Traced neurons. These are
  workflow annotations; they do not establish whether proofreading is
  currently active. Synapse counts are reconstructed from automated
  detection, with no claim of finished, manually verified connectivity
  everywhere.
- `receptorType` covers only 0.4% of rows - not usable as a general field.
- `consensusNt` vs `predictedNt` disagree on 10.78% of the 187,016 rows
  where both are populated (3.21% if you exclude either field's "unclear"
  value) - a real curation/prediction gap, not a bug. (A ~25% figure
  measured elsewhere on the much smaller 1,021-neuron seed-circuit subset
  isn't comparable - don't conflate the two.)
- `class` is 100% missing for every motor/endocrine/efferent neuron -
  the input and output classification pipelines are structurally
  different for this reason, not by choice.
- Several R->Python numeric-type mismatches were found and fixed at the
  `load_data.py` boundary (R writing bodyids/weights as scientific-notation
  or double-precision text, polars inferring the wrong dtype) - anyone
  extending this pipeline should read that module's docstring first.

## 6. Exploring it yourself

Start with **Start Here** for dataset scope and navigation, then **ML Primer**
for the distinction between wiring, activity and learning. Its longer
[ML cheat sheet](ml_cheat_sheet.md) includes an example dynamics model,
source-linked circuit analogies and reproducible graph statistics.

```sh
cd app && python3 -m http.server 8000
# open http://localhost:8000
```

- **View 1 (Overview)**: selected input→processing→output Sankey, switch the link-width
  metric (synapse weight / unique edges / unique neurons).
- **View 2 (I/O Matrix)**: heatmap over all 80 category pairs, switch
  metric, click a cell to drill down.
- **View 3 (Pathway Explorer)**: reduced subgraph for one pair, starts
  aggregated by cell type, click to expand, filter by superclass / class
  / neurotransmitter / soma side / min weight / max hops / name search.
- **View 4 (Neuron Detail)**: full metadata + strongest partners for any
  neuron you've clicked into, plus a 3D morphology viewer where available.
- **View 5 (Dynamics)**: illustrative leaky-integrator simulation on the
  24-layer aggregate graph - a coarse, explicitly non-physiological demo,
  not a validated model (see `src/io_analysis/dynamics.py`).
- **View 6/7 (Anatomy 2D/3D)**: the 140,024 of 165,122 traced neurons
  (84.8%) with recorded EM-volume soma positions, colored by `io_role`.
  The 3D view displays a subset by default for responsiveness.
- **Global search**: across all 165,122 traced neurons, not just the
  6,895 reachable through a precomputed pathway drill-down.

## 7. What's not done yet

- **Phase 11** (directory reshuffle): current layout already matches the
  target structure closely; no forced reorganization has been done.
- **Phase 12** (`results/io_census_report.txt` exists from Phase 1, but
  the later validation report covering classification/connectivity/matrix
  together hasn't been written).
- Neurotransmitter perturbation on top of the Dynamics simulation was
  built and then removed - tested unconvincing/unreadable in practice.
