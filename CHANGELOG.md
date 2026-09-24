# Changelog

## 1.0.0 — 2026-09-24

First stable release of Drosophila Under the Hood, a data engineering and
connectomics exploration tool built on the public MaleCNS connectome.
The underlying reconstruction is the work of the MaleCNS collaboration.

### Included

- R extraction from neuPrint, Python I/O classification and graph analysis,
  and static JSON exports for a JavaScript explorer with no backend.
- Sankey overview, I/O matrix, pathway drill-down, global neuron search,
  per-neuron morphology, and whole-connectome 2D/3D anatomy views.
- An illustrative leaky-integrator simulation on the aggregated graph.
- Input and manifest validation, strict JSON export, classifier source
  provenance, and regression tests for classification, graph metrics,
  pathways, loaders, and exports.
- Frontend state regression tests covering asynchronous pathway and search
  loading, neuron-detail resets, and restoration of views from shared URLs.

### Scope and limitations

- The source is a reconstruction of one male animal. Annotation-derived
  I/O roles are exploratory groupings, with confidence caveats documented
  in [the classification rules](docs/io_classification_rules.md).
- Weighted shortest paths and max-flow describe graph topology under
  synapse-count-based costs and capacities; they do not measure biological
  signal strength. The dynamics demo is not a validated physiological model.
- Raw connectivity, the search index, and per-neuron morphology assets are
  excluded from Git. Follow the [README pipeline](README.md#pipeline) to
  regenerate them for a complete local build or deployment.
- Code is MIT-licensed; source data and data-derived exports are subject to
  CC-BY 4.0 attribution. See [data and citation](README.md#data--citation)
  and [LICENSE](LICENSE).

The project release, source dataset (`male-cns:v1.0`), and classification
rules have independent versions. This release identifies a software
milestone, not scientific validation of the derived models.
