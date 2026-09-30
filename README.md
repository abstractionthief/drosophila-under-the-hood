# Drosophila Under the Hood

An exploration of the Janelia **male *Drosophila* CNS connectome**
(`male-cns:v1.0`) — a full R → Python → interactive-app pipeline that goes
from raw neuPrint queries to a whole-connectome I/O map, a leaky-integrator
dynamics demo, and a real-anatomy 3D/2D visualization of the 140,024 traced
neurons (84.8% of all 165,122) with a recorded soma position.

See [`docs/project_overview.md`](docs/project_overview.md) for the full
architecture and biological narrative.

The app's **ML Primer** introduces activity, recurrent computation and
controlled experiments. Its [longer cheat sheet](docs/ml_cheat_sheet.md)
includes modelling assumptions, sources and reproducible graph statistics.

Project release: **1.0.0** — see [release notes](CHANGELOG.md).
The project version is independent of the source dataset version
(`male-cns:v1.0`) and the classification rule version recorded in exports.

## Data & citation

Dataset: `male-cns:v1.0`, licensed
[**CC-BY 4.0**](https://creativecommons.org/licenses/by/4.0/) by FlyEM
(HHMI Janelia), the Cambridge Drosophila Connectomics Group / MRC LMB, and
Google Research.

If you use or build on this data, cite:

> Berg, S., Beckett, I.R., Costa, M., et al. "Sexual dimorphism in the
> complete connectome of the *Drosophila* male central nervous system."
> *Cell* 189(18), 5504-5526 (2026). DOI:
> [10.1016/j.cell.2026.08.015](https://doi.org/10.1016/j.cell.2026.08.015).
> (Preprint: [bioRxiv 10.1101/2025.10.09.680999](https://doi.org/10.1101/2025.10.09.680999).)

Accessed via [neuPrint](https://neuprint.janelia.org) through the
[`malecns`](https://github.com/natverse/malecns) R package.

## Prerequisites

- R (>= 3.5)
- The `malecns` package and its dependencies (installed manually, per the
  [malecns README](https://github.com/natverse/malecns#installation)):

  ```r
  install.packages("natmanager")
  natmanager::install(pkgs = "natverse/malecns")
  install.packages(c("arrow", "jsonlite", "dplyr"))
  ```

  `arrow` writes the connectivity and skeleton Parquet files; `jsonlite`
  and `dplyr` support the extraction scripts.

- A neuPrint token, set as `NEUPRINT_TOKEN` in your `~/.Renviron` (see
  [neuprintr authentication](https://github.com/natverse/neuprintr#authentication)).
  Never commit this token; `.gitignore` already excludes `.Renviron` and `.env` files.
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) for the analysis layer.

## Pipeline

```sh
# 1. R: extract the census, connectivity, and neuron positions
Rscript r/build_io_census.R
Rscript r/build_io_connectivity.R
Rscript r/build_neuron_positions.R

# 2. Python: classify, aggregate, build graphs/matrix/pathways, simulate
uv sync
uv run python -m io_analysis.classification
uv run python -m io_analysis.aggregation
uv run python -m io_analysis.graph
uv run python -m io_analysis.dynamics
uv run python -m io_analysis.export_positions
uv run python -m io_analysis.export_app_data
uv run python -m io_analysis.export_start_animation
uv run python -m io_analysis.primer_stats

# 3. Global search + per-neuron 3D morphology (needs app/data/pathways/
# from export_app_data above; the R step needs data/skeleton_bodyids.csv
# from list_skeleton_targets, and takes about an hour for 6,895 neurons)
uv run python -m io_analysis.list_skeleton_targets
Rscript r/build_neuron_skeletons.R
uv run python -m io_analysis.export_skeletons
uv run python -m io_analysis.export_search_index

# 4. Serve the app
cd app && python3 -m http.server 8000
# open http://localhost:8000
```

`r/smoke_test.R` and `r/inspect_neuron.R` are standalone diagnostics, not
part of the main pipeline - run them any time to sanity-check the neuPrint
connection.

The app export also refreshes `data/io_matrix.csv` and any existing
standalone examples under `data/pathways/` from the same results used for
the browser JSON. The manifest records the complete classifier source
hash and whether the recorded Git commit has local changes.

Without step 3, the app still works, but global search and the Neuron
Detail 3D morphology viewer have nothing to fetch - both `app/data/skeletons/`
and `app/data/search_index.json` are gitignored (287MB combined) and must be
generated locally.

## Testing

```sh
uv run pytest tests/
# Frontend state regressions (Node.js 18+; no npm dependencies):
node --test tests/app_state.test.cjs
```

Tests cover classification, graph metrics, pathway pruning, data loaders,
and browser exports using small graphs and synthetic files. Regression
cases include motor-target precedence, complete-route preservation,
invalid IDs/weights, mismatched manifests, undefined normalization,
coverage accounting, and CSV/JSON agreement.

Frontend tests cover responses arriving out of order, clearing neuron details,
restoring linked views, and searches waiting for the index. They stub plotting
and layout; visual behavior still needs a browser check.

## Structure

```
r/            R extraction scripts (neuPrint -> CSV/Parquet)
src/io_analysis/   Python analysis (classification, graphs, dynamics, app data export)
tests/        Unit/regression tests for src/io_analysis (uv run pytest tests/)
app/          Static interactive explorer (no backend)
data/         Extracted/derived tables (large raw files gitignored)
docs/         Architecture overview, build log, domain reference, classification rules
results/      Validation reports
```
