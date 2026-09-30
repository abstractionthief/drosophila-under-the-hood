// MaleCNS I/O Explorer - static client, no backend. Data is precomputed JSON
// under data/. Views 1-2 are whole-connectome aggregates; View 3 is a
// reduced per-category-pair subgraph; View 4 is a neuron's detail, derived
// only from neurons already present in a loaded drill-down.

const ROLE_COLORS = {
  sensory_input: "#2e7d32",
  central_processing: "#1565c0",
  descending: "#ef6c00",
  vnc: "#6a1b9a",
  motor: "#c62828",
  other: "#8a8a94",
};
const STAGE_COLORS = { input: "#2e7d32", processing: "#1565c0", output: "#c62828" };

let sankeyData = null;
let matrixData = null;
let pathwayData = null; // currently loaded {input_category, output_category, params, nodes, edges, paths}
// set by loadPathway(); re-applied once matrix.json's <option>s exist (deep-link race)
let pendingPathwaySelectKey = null;
let expandedTypes = new Set();
let cy = null;
let lastSelectedBodyid = null;
let pathwayRequestId = 0;

// ---------- theming ----------
// Plotly bakes colors into each figure at render time, so a data-theme
// change alone doesn't repaint - refreshAllCharts() re-runs every loaded renderer.

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function gridColor() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "#2a2a2a" : "#eeeeee";
}

// Shallow merge only - callers setting xaxis/yaxis must include
// gridcolor: gridColor() themselves, or `extra` silently replaces these defaults.
function plotlyThemeLayout(extra) {
  return Object.assign(
    {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: cssVar("--text"), size: 11 },
    },
    extra
  );
}

function refreshAllCharts() {
  if (sankeyData) renderSankey(document.getElementById("sankey-metric").value);
  if (matrixData) renderMatrix(document.getElementById("matrix-metric").value);
  if (dynamicsData) { renderDynamicsFrame(); renderDynamicsLines(document.getElementById("dynamics-stimulus").value); }
  if (positionsData) { renderAnatomy(); renderAnatomy3D(); }
  if (cy) cy.style().update();
  if (lastSelectedBodyid) renderSkeleton(lastSelectedBodyid);
}

document.getElementById("theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) {}
  refreshAllCharts();
});

// #header-body needs the same `inert` treatment as the disclosure panels below.
const headerBody = document.getElementById("header-body");
headerBody.inert = document.documentElement.getAttribute("data-header") === "collapsed";

document.getElementById("header-toggle").addEventListener("click", (e) => {
  const collapsed = document.documentElement.getAttribute("data-header") === "collapsed";
  const next = collapsed ? "expanded" : "collapsed";
  document.documentElement.setAttribute("data-header", next);
  headerBody.inert = next === "collapsed";
  const btn = e.currentTarget;
  btn.setAttribute("aria-expanded", String(collapsed));
  btn.title = collapsed ? "Hide header" : "Show header";
  try { localStorage.setItem("headerCollapsed", next === "collapsed" ? "1" : "0"); } catch (e) {}
  positionHeaderControls();
  // resize once the 0.2s collapse transition finishes
  setTimeout(resizeActivePlots, 240);
});

// Toggles a collapsible panel's aria-expanded/open class and resizes charts
// after the transition. `inert` keeps a closed panel's controls out of the
// tab order - max-height:0 hides them visually but not from keyboard focus.
function bindDisclosureToggle(toggleId, panelId) {
  const panel = document.getElementById(panelId);
  panel.inert = true;
  document.getElementById(toggleId).addEventListener("click", (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute("aria-expanded") === "true";
    const nowOpen = !open;
    btn.setAttribute("aria-expanded", String(nowOpen));
    panel.classList.toggle("open", nowOpen);
    panel.inert = !nowOpen;
    setTimeout(resizeActivePlots, 220);
  });
}
bindDisclosureToggle("filter-toggle", "filter-panel");
bindDisclosureToggle("details-toggle", "details-panel");
bindDisclosureToggle("category-legend-toggle", "category-legend-panel");
bindDisclosureToggle("coverage-panel-toggle", "coverage-panel");

document.querySelectorAll(".info-disclosure").forEach((panel) => {
  panel.addEventListener("toggle", () => requestAnimationFrame(resizeActivePlots));
});

// ---------- nav ----------
// Every tab fills the viewport with no page scroll (see .fill in style.css),
// so any layout change needs an explicit Plotly resize() - it doesn't watch
// its container continuously on its own.
function resizeActivePlots() {
  const active = document.querySelector("nav button.active");
  if (!active) return;
  const view = active.dataset.view;
  try {
    if (view === "matrix" && matrixData) Plotly.Plots.resize("heatmap");
    if (view === "overview" && sankeyData) Plotly.Plots.resize("sankey");
    if (view === "dynamics" && dynamicsData) {
      Plotly.Plots.resize("dynamics-bars");
      Plotly.Plots.resize("dynamics-lines");
    }
    if (view === "anatomy" && positionsData) Plotly.Plots.resize("anatomy-plot");
    if (view === "anatomy3d" && positionsData) Plotly.Plots.resize("anatomy3d-plot");
    if (view === "pathway" && cy) cy.resize();
    if (view === "detail" && lastSelectedBodyid) Plotly.Plots.resize("detail-skeleton-plot");
  } catch (e) { /* chart not rendered yet - fine, nothing to resize */ }
}

// ---------- deep links ----------
// Current tab/pathway/neuron reflected in the URL (?view=&pathway=&bodyid=)
// via replaceState, never pushState - not meant to spam back-button history.
function updateURLState() {
  const params = new URLSearchParams();
  const active = document.querySelector("nav button.active");
  if (active) params.set("view", active.dataset.view);
  // pathwayData.params has no input/output category pair - the <select> is the source of truth
  const pathwayKey = document.getElementById("pathway-select").value;
  if (pathwayData && pathwayKey) params.set("pathway", pathwayKey);
  if (lastSelectedBodyid != null && (active?.dataset.view === "detail" || active?.dataset.view === "pathway")) {
    params.set("bodyid", lastSelectedBodyid);
  }
  const qs = params.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("view-" + btn.dataset.view).classList.add("active");
    // let layout settle (view just became display:flex) before measuring
    requestAnimationFrame(resizeActivePlots);
    updateURLState();
  });
});

// Fixed, not measured: getBoundingClientRect() on this CSS-scaled element
// reports the shrunk size while hidden, throwing off the centering math.
const LOGO_MINI_SIZE = 82;
const HEADER_COLLAPSED_HEIGHT = 76; // keep in sync with `header { min-height }` in style.css

const HEADER_CONTROLS_SIZE = 34; // matches #theme-toggle/#header-toggle's CSS width/height

// Collapsed header + nav read as one blank rectangle - center the mini logo
// and header-controls across both, not just the header's own slice.
function combinedHeaderNavCenter() {
  const nav = document.querySelector("nav");
  if (!nav) return HEADER_COLLAPSED_HEIGHT / 2;
  const navHeight = nav.getBoundingClientRect().height;
  return (HEADER_COLLAPSED_HEIGHT + navHeight) / 2;
}

function positionLogoMini() {
  const logo = document.querySelector(".logo-mini");
  const firstTab = document.querySelector("nav button");
  if (!logo || !firstTab) return;

  // Centered in the gutter left of the nav tabs; width depends on window/tab
  // sizes, so it's measured, not fixed.
  const gutter = firstTab.getBoundingClientRect().left;
  logo.style.left = Math.max(12, (gutter - LOGO_MINI_SIZE) / 2) + "px";
  logo.style.top = (combinedHeaderNavCenter() - LOGO_MINI_SIZE / 2) + "px";
}

function positionHeaderControls() {
  const controls = document.querySelector(".header-controls");
  if (!controls) return;
  const collapsed = document.documentElement.getAttribute("data-header") === "collapsed";
  // Expanded: leave CSS's own top:20px. Collapsed: center like the mini logo.
  controls.style.top = collapsed ? (combinedHeaderNavCenter() - HEADER_CONTROLS_SIZE / 2) + "px" : "";
}

let resizeDebounce = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeDebounce);
  resizeDebounce = setTimeout(() => { resizeActivePlots(); positionLogoMini(); positionHeaderControls(); }, 100);
});
positionLogoMini();
positionHeaderControls();
if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { positionLogoMini(); positionHeaderControls(); });

function showView(name) {
  document.querySelector(`nav button[data-view="${name}"]`).click();
}

document.querySelectorAll("a[data-jump]").forEach((a) => {
  a.addEventListener("click", (e) => {
    // Keep the example's real URL usable in a new tab as well.
    if (a.dataset.pathway && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return;
    e.preventDefault();
    if (a.dataset.pathway) {
      const [inputCat, outputCat] = a.dataset.pathway.split("__");
      const bodyid = a.dataset.bodyid ? Number(a.dataset.bodyid) : undefined;
      loadPathway(inputCat, outputCat, bodyid, a.dataset.jump);
      return;
    }
    showView(a.dataset.jump);
  });
});

// ---------- Phase 10: provenance ----------
// Kept as two blocks: #prov-dataset is raw extraction facts, #prov-analysis
// is our own analytical choices (classification rules, thresholds).
let manifestData = null;

fetch("data/manifest.json")
  .then((r) => r.json())
  .then((m) => {
    manifestData = m;
    document.getElementById("prov-dataset").textContent =
      `dataset: ${m.dataset} · edges extracted ${m.edge_extraction_timestamp_utc} · ` +
      `node count (traced): ${m.node_count_traced} (raw census: ${m.node_count_total_census}) · ` +
      `edge count: ${typeof m.edge_count === "number" ? m.edge_count.toLocaleString() : "unknown (edges manifest missing at export time)"}`;
    document.getElementById("prov-analysis").textContent =
      `analysis: classification rules ${m.classification_rule_version} (${m.classification_rule_hash}) · ` +
      `pathway drill-down defaults: max_hops=${m.pathway_default_params.max_hops}, ` +
      `min_weight=${m.pathway_default_params.minimum_weight}, max_nodes=${m.pathway_default_params.max_nodes} · ` +
      `exported ${m.app_export_timestamp_utc}` +
      (m.git_commit ? ` · commit ${m.git_commit.slice(0, 12)}` : "") +
      (m.git_dirty ? " (with local changes)" : "");
    populateCategoryLegend(m.category_counts);
    refreshCoveragePanel();
  })
  .catch(() => {
    document.getElementById("prov-dataset").textContent = "manifest.json not found. Run io_analysis.export_app_data first.";
    document.getElementById("prov-analysis").textContent = "";
  });

document.getElementById("prov-download").addEventListener("click", () => {
  if (!manifestData) return;
  const blob = new Blob([JSON.stringify(manifestData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "malecns-io-explorer-provenance.json";
  // Must be attached to the DOM for the click to reliably trigger a
  // download in every browser - a detached anchor's click is not always
  // enough. Revoke the object URL on a delay, not synchronously - revoking
  // immediately after click() can race the browser's own download start.
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

// Fills the category-legend table's counts from manifest.json's
// category_counts (computed by export_app_data.py straight from
// classification.py's output) instead of hand-maintained numbers, which
// went stale the first time the classifier changed.
function populateCategoryLegend(counts) {
  if (!counts) return;
  document.querySelectorAll("[data-count]").forEach((td) => {
    const [group, key] = td.dataset.count.split(".");
    const n = counts[group]?.[key];
    td.textContent = typeof n === "number" ? n.toLocaleString() : "?";
  });
  document.getElementById("category-legend-hint").innerHTML =
    `Counts are generated from the current classification export. "unknown" ` +
    `(${counts.unknown.toLocaleString()} neurons, ${(100 * counts.unknown / counts.total_census).toFixed(1)}% ` +
    `of census) is a deliberate residual bucket: mostly non-traced bodies or dataset-flagged ` +
    `uncertainty, not a real category. Output categories are derived primarily from a motor ` +
    `neuron's own documented <code>subclass</code> label, falling back to <code>exitNerve</code> ` +
    `(external MANC nerve nomenclature) only where subclass doesn't resolve it.`;
}

// Pulls together every "how much of this can you actually trust" number this
// project has had to re-derive by hand across several review rounds
// (reconstruction status, missing metadata, output-classification method,
// soma-position and 3D-morphology coverage) into one place, instead of
// leaving a reader to piece it together from scattered caveats per tab.
// Called from each of the three source fetches (manifest/positions/skeleton
// manifest) since they load independently and any of them may still be in
// flight when another completes - each call fills in whatever it can.
function refreshCoveragePanel() {
  const el = document.getElementById("coverage-panel-content");
  if (!el || !manifestData?.coverage) return;
  const c = manifestData.coverage;
  const pct = (n, d) => (d ? `${(100 * n / d).toFixed(1)}%` : "?");

  const roughlyTraced = (c.traced_status_label_counts["Roughly traced"] || 0)
    + (c.traced_status_label_counts["Prelim Roughly traced"] || 0);

  const somaLine = positionsData
    ? `${positionsData.n.toLocaleString()} / ${c.traced.toLocaleString()} Traced neurons (${pct(positionsData.n, c.traced)}) have a recorded soma position (Anatomy views).`
    : "soma position coverage: loading...";
  const skelLine = skeletonManifest
    ? `${skeletonManifest.bodyids.length.toLocaleString()} / ${c.traced.toLocaleString()} Traced neurons (${pct(skeletonManifest.bodyids.length, c.traced)}) are reachable through a precomputed pathway drill-down and have 3D morphology available.`
    : "3D morphology coverage: loading...";

  el.innerHTML = `
    <ul class="coverage-list">
      <li><strong>Reconstruction status:</strong> ${c.traced.toLocaleString()} / ${c.total_census.toLocaleString()} bodies (${pct(c.traced, c.total_census)}) carry status <code>Traced</code>. Of those, ${roughlyTraced.toLocaleString()} (${pct(roughlyTraced, c.traced)}) carry <code>Roughly traced</code> or <code>Prelim Roughly traced</code> workflow annotations. These labels are not a uniform completeness guarantee and do not establish whether proofreading is currently active.</li>
      <li><strong>Missing/uncertain classification input:</strong> ${c.superclass_missing.toLocaleString()} rows have no <code>superclass</code> at all (mostly non-Traced bodies); ${c.superclass_tbc.toLocaleString()} carry the dataset's own <code>_tbc</code> ("to be confirmed") marker; ${c.sensory_class_missing.toLocaleString()} / ${c.sensory_total.toLocaleString()} sensory-superclass rows have no <code>class</code>. All of these land in <code>unknown</code>, never guessed.</li>
      <li><strong>Output-category method:</strong> of ${c.output_category_total.toLocaleString()} output-role neurons, ${c.output_category_subclass_derived.toLocaleString()} (${pct(c.output_category_subclass_derived, c.output_category_total)}) are classified directly from their documented motor <code>subclass</code>; ${c.output_category_exit_nerve_fallback.toLocaleString()} (${pct(c.output_category_exit_nerve_fallback, c.output_category_total)}) receive a category through the lower-confidence <code>exitNerve</code> mapping; ${c.output_category_unknown.toLocaleString()} (${pct(c.output_category_unknown, c.output_category_total)}) remain <code>unknown</code>.</li>
      <li><strong>Soma position:</strong> ${somaLine}</li>
      <li><strong>3D morphology:</strong> ${skelLine}</li>
    </ul>
  `;
}

// ---------- View 1: Overview Sankey ----------
const SANKEY_METRIC_LABELS = {
  total_weight: "Synapse weight (raw synapse count sum) [dataset value]",
  n_directed_connections: "Unique edges (distinct neuron-neuron connections) [dataset value]",
  n_unique_neurons: "Unique neurons (distinct source-side neurons) [dataset value]",
};

function renderSankey(metric) {
  document.getElementById("sankey-active-metric").textContent = `Active metric: ${SANKEY_METRIC_LABELS[metric]}`;
  const nodes = sankeyData.nodes;
  const links = sankeyData.links;
  Plotly.react(
    "sankey",
    [
      {
        type: "sankey",
        orientation: "h",
        node: {
          label: nodes.map((n) => n.name),
          color: nodes.map((n) => STAGE_COLORS[n.stage]),
          pad: 10,
          thickness: 14,
        },
        link: {
          source: links.map((l) => l.source),
          target: links.map((l) => l.target),
          value: links.map((l) => l[metric]),
          // Plotly's default link color is a light grey that's fine on
          // white but glaringly bright on a black dark-mode background -
          // pick one neutral semi-transparent grey that reads fine either way.
          color: "rgba(140,140,140,0.35)",
        },
      },
    ],
    plotlyThemeLayout({ margin: { l: 10, r: 10, t: 10, b: 10 } }),
    { responsive: true }
  );
}

fetch("data/sankey.json")
  .then((r) => r.json())
  .then((d) => {
    sankeyData = d;
    renderSankey("total_weight");
    document.getElementById("sankey-metric").addEventListener("change", (e) => renderSankey(e.target.value));
  })
  .catch(() => {
    document.getElementById("sankey-active-metric").textContent =
      "data/sankey.json not found. Run `uv run python -m io_analysis.export_app_data` first.";
  });

// ---------- View 2: I/O Matrix heatmap ----------
// "n_pairs_within_hops" is a stable key (see graph.py); the actual hop bound
// comes from matrixData.n_pairs_within_hops_value, not a hardcoded label.
function matrixMetricLabels() {
  const hops = matrixData?.n_pairs_within_hops_value ?? "?";
  return {
    shortest_path_hops: "Shortest path (hops, unweighted) [derived metric]",
    weighted_shortest_path: "Weighted shortest path (topological, cost=1/weight) [derived metric]",
    n_pairs_within_hops: `Neuron pairs within ${hops} hops (exact pairwise count) [derived metric]`,
    max_flow: "Max-flow (topological, capacity=weight) [derived metric]",
    max_flow_frac_of_input_output: "Max-flow / input category's total output (normalized, 0-1) [derived metric]",
    max_flow_frac_of_output_input: "Max-flow / output category's total input (normalized, 0-1) [derived metric]",
  };
}

function renderMatrix(metric) {
  document.getElementById("matrix-active-metric").textContent = `Active metric: ${matrixMetricLabels()[metric]}`;
  const inputs = matrixData.input_categories;
  const outputs = matrixData.output_categories;
  const z = inputs.map((ic) =>
    outputs.map((oc) => {
      const cell = matrixData.cells.find((c) => c.input_category === ic && c.output_category === oc);
      return cell ? cell[metric] : null;
    })
  );
  const heatmapDiv = document.getElementById("heatmap");
  Plotly.react(
    heatmapDiv,
    [
      {
        type: "heatmap",
        x: outputs,
        y: inputs,
        z: z,
        colorscale: "Viridis",
        hovertemplate: "%{y} -> %{x}<br>" + metric + ": %{z}<extra></extra>",
      },
    ],
    plotlyThemeLayout({ margin: { l: 120, r: 10, t: 10, b: 80 } }),
    { responsive: true }
  );
  heatmapDiv.removeAllListeners && heatmapDiv.removeAllListeners("plotly_click");
  heatmapDiv.on("plotly_click", (ev) => {
    const p = ev.points[0];
    const inputCat = p.y, outputCat = p.x;
    loadPathway(inputCat, outputCat);
  });
}

fetch("data/matrix.json")
  .then((r) => r.json())
  .then((d) => {
    matrixData = d;
    renderMatrix("shortest_path_hops");
    document.getElementById("matrix-metric").addEventListener("change", (e) => renderMatrix(e.target.value));

    const sel = document.getElementById("pathway-select");
    for (const ic of d.input_categories) {
      for (const oc of d.output_categories) {
        const opt = document.createElement("option");
        opt.value = `${ic}__${oc}`;
        opt.textContent = `${ic} -> ${oc}`;
        sel.appendChild(opt);
      }
    }
    // loadPathway() may have already tried (and silently failed, since these
    // options didn't exist yet) to set this - apply it again now that they do.
    if (pendingPathwaySelectKey) sel.value = pendingPathwaySelectKey;

    sel.addEventListener("change", (e) => {
      if (!e.target.value) return;
      const [ic, oc] = e.target.value.split("__");
      loadPathway(ic, oc);
    });
  })
  .catch(() => {
    document.getElementById("matrix-active-metric").textContent =
      "data/matrix.json not found. Run `uv run python -m io_analysis.export_app_data` first.";
  });

// ---------- View 3: Pathway Explorer ----------
function loadPathway(inputCat, outputCat, focusBodyid, targetView) {
  const requestId = ++pathwayRequestId;
  return fetch(`data/pathways/${inputCat}__${outputCat}.json`)
    .then((r) => {
      if (!r.ok) throw new Error("no precomputed drill-down for this pair");
      return r.json();
    })
    .then((d) => {
      // Responses can arrive out of order. Only the latest selection may
      // update the graph, details, selected option, or URL.
      if (requestId !== pathwayRequestId) return;
      pathwayData = d;
      expandedTypes = new Set();
      hopDistanceCache = null;
      clearNeuronDetail();
      pendingPathwaySelectKey = `${inputCat}__${outputCat}`;
      document.getElementById("pathway-select").value = pendingPathwaySelectKey;
      showView("pathway");
      const p = d.params;
      document.getElementById("pathway-build-provenance").textContent =
        `This reduced subgraph was built with: max_hops=${p.max_hops}, minimum_weight=${p.minimum_weight}, ` +
        `max_nodes=${p.max_nodes}, top_n_paths=${p.top_n_paths} (analysis parameters, not raw dataset facts). ` +
        `Filters below only narrow what's already loaded; see live status for currently active thresholds.`;
      initFilters();

      if (focusBodyid != null) {
        const n = nodeById(focusBodyid);
        if (n) {
          expandedTypes.add(n.type || "(no type)");
          lastSelectedBodyid = focusBodyid;
        }
      }
      renderPathwayGraph();
      renderPathsTable();
      if (focusBodyid != null && nodeById(focusBodyid)) {
        renderNeuronDetail(focusBodyid);
        showView(targetView || "detail");
      } else {
        showView(targetView || "pathway");
      }
    })
    .catch((err) => {
      if (requestId === pathwayRequestId) alert(err.message);
    });
}

// Reads ?view=...&pathway=<input>__<output>&bodyid=... on first load and
// reproduces that state - the read side of the deep-link pair (write
// side is updateURLState(), called on every view/pathway/neuron change).
function applyInitialDeepLink() {
  const params = new URLSearchParams(location.search);
  const pathway = params.get("pathway");
  const bodyidStr = params.get("bodyid");
  const bodyid = bodyidStr ? Number(bodyidStr) : null;
  const view = params.get("view");
  const validView = Array.from(document.querySelectorAll("nav button"))
    .some((button) => button.dataset.view === view);

  if (pathway && pathway.includes("__")) {
    const [ic, oc] = pathway.split("__");
    loadPathway(ic, oc, bodyid ?? undefined, validView ? view : undefined);
    return;
  }
  if (validView) showView(view);
  if (bodyid != null) {
    // No ?pathway= given - look up which one (if any) this bodyid belongs
    // to via the search index, same data the search feature itself uses.
    // Preserve an explicit tab once the supporting pathway has loaded;
    // without one, a neuron-only link defaults to its detail view.
    searchIndexReady.then(() => {
      const row = (searchRows || []).find((r) => r.bodyid === bodyid);
      if (row && row.pathway_key) {
        const [ic, oc] = row.pathway_key.split("__");
        loadPathway(ic, oc, bodyid, validView ? view : undefined);
      }
    });
  }
}

function nodeById(bodyid) {
  return pathwayData.nodes.find((n) => n.bodyid === bodyid);
}

// ---------- Phase 9: filters (non-destructive - only toggle cy element
// visibility on top of the already-loaded pathway; never touch the
// underlying JSON/CSV datasets). ----------

let hopDistanceCache = null; // bodyid -> hops from nearest sensory_input node, within this pathway

function computeHopDistances() {
  if (hopDistanceCache) return hopDistanceCache;
  const dist = new Map();
  const queue = [];
  pathwayData.nodes.forEach((n) => {
    if (n.role_group === "sensory_input") { dist.set(n.bodyid, 0); queue.push(n.bodyid); }
  });
  const adj = new Map();
  pathwayData.edges.forEach((e) => {
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source).push(e.target);
  });
  let head = 0;
  while (head < queue.length) {
    const cur = queue[head++];
    const d = dist.get(cur);
    for (const nxt of adj.get(cur) || []) {
      if (!dist.has(nxt)) { dist.set(nxt, d + 1); queue.push(nxt); }
    }
  }
  hopDistanceCache = dist;
  return dist;
}

function distinctValues(field) {
  const vals = new Set();
  pathwayData.nodes.forEach((n) => { if (n[field] != null && n[field] !== "") vals.add(n[field]); });
  return Array.from(vals).sort();
}

function fillMultiSelect(id, values) {
  const el = document.getElementById(id);
  el.innerHTML = "";
  values.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v; opt.textContent = v;
    el.appendChild(opt);
  });
}

function initFilters() {
  fillMultiSelect("f-superclass", distinctValues("superclass"));
  fillMultiSelect("f-class", distinctValues("class"));
  fillMultiSelect("f-nt", distinctValues("consensusNt"));
  fillMultiSelect("f-somaside", distinctValues("somaSide"));

  const maxW = Math.max(...pathwayData.edges.map((e) => e.weight), 1);
  const wSlider = document.getElementById("f-weight");
  wSlider.min = 1; wSlider.max = maxW; wSlider.value = pathwayData.params.minimum_weight || 1;
  document.getElementById("f-weight-out").textContent = wSlider.value;

  const hSlider = document.getElementById("f-hops");
  hSlider.max = pathwayData.params.max_hops || 3;
  hSlider.value = hSlider.max;
  document.getElementById("f-hops-out").textContent = hSlider.value;

  document.getElementById("f-search").value = "";
}

function selectedValues(id) {
  return Array.from(document.getElementById(id).selectedOptions).map((o) => o.value);
}

function currentFilters() {
  return {
    superclass: selectedValues("f-superclass"),
    klass: selectedValues("f-class"),
    nt: selectedValues("f-nt"),
    somaSide: selectedValues("f-somaside"),
    minWeight: Number(document.getElementById("f-weight").value),
    maxHops: Number(document.getElementById("f-hops").value),
    search: document.getElementById("f-search").value.trim().toLowerCase(),
  };
}

function nodePassesFilter(n, f, hops) {
  if (f.superclass.length && !f.superclass.includes(n.superclass)) return false;
  if (f.klass.length && !f.klass.includes(n.class)) return false;
  if (f.nt.length && !f.nt.includes(n.consensusNt)) return false;
  if (f.somaSide.length && !f.somaSide.includes(n.somaSide)) return false;
  // Undefined = unreachable from any sensory_input node in this subgraph,
  // not "0 hops away" - must fail any finite hops filter too.
  const h = hops.get(n.bodyid) ?? Infinity;
  if (h > f.maxHops) return false;
  if (f.search) {
    const hay = `${n.type || ""} ${n.name || ""}`.toLowerCase();
    if (!hay.includes(f.search)) return false;
  }
  return true;
}

// Aggregates only edges whose *individual* weight and both endpoint neurons
// currently pass filters - summing first and thresholding the sum (the
// previous approach) let a collapsed link built from several under-threshold
// or filtered-out edges pass anyway, then vanish inconsistently on expand.
function computeFilteredEdgeAgg(passByBodyid, f) {
  const edgeAgg = {};
  pathwayData.edges.forEach((e) => {
    if (e.weight < f.minWeight) return;
    if (!passByBodyid.get(e.source) || !passByBodyid.get(e.target)) return;
    const key = visibleId(e.source) + "->" + visibleId(e.target);
    edgeAgg[key] = (edgeAgg[key] || 0) + e.weight;
  });
  return edgeAgg;
}

function applyFilters() {
  if (!cy || !pathwayData) return;
  const f = currentFilters();
  const hops = computeHopDistances();

  const passByBodyid = new Map();
  pathwayData.nodes.forEach((n) => passByBodyid.set(n.bodyid, nodePassesFilter(n, f, hops)));

  cy.nodes().forEach((cn) => {
    if (cn.data("kind") === "neuron") {
      cn.style("display", passByBodyid.get(cn.data("bodyid")) ? "element" : "none");
    } else {
      // aggregate "type" node: visible if at least one member currently passes
      const anyPass = pathwayData.nodes.some(
        (n) => (n.type || "(no type)") === cn.data("typeName") && passByBodyid.get(n.bodyid)
      );
      cn.style("display", anyPass ? "element" : "none");
    }
  });

  cy.batch(() => {
    cy.edges().remove();
    const edgeAgg = computeFilteredEdgeAgg(passByBodyid, f);
    for (const [key, w] of Object.entries(edgeAgg)) {
      const [s, tg] = key.split("->");
      cy.add({ data: { id: "e:" + key, source: s, target: tg, weight: w } });
    }
  });

  const shownNodes = cy.nodes().filter((n) => n.style("display") !== "none").length;
  const activeBits = [`min_weight>=${f.minWeight}`, `hops<=${f.maxHops}`];
  if (f.superclass.length) activeBits.push(`superclass in {${f.superclass.join(", ")}}`);
  if (f.klass.length) activeBits.push(`class in {${f.klass.join(", ")}}`);
  if (f.nt.length) activeBits.push(`consensusNt in {${f.nt.join(", ")}}`);
  if (f.somaSide.length) activeBits.push(`somaSide in {${f.somaSide.join(", ")}}`);
  if (f.search) activeBits.push(`search="${f.search}"`);
  document.getElementById("f-status").textContent =
    `Showing ${shownNodes} / ${cy.nodes().length} nodes · active thresholds: ${activeBits.join(", ")} ` +
    `(filters affect visibility only; underlying data is unchanged).`;
}

["f-superclass", "f-class", "f-nt", "f-somaside"].forEach((id) =>
  document.getElementById(id).addEventListener("change", applyFilters)
);
document.getElementById("f-weight").addEventListener("input", (e) => {
  document.getElementById("f-weight-out").textContent = e.target.value;
  applyFilters();
});
document.getElementById("f-hops").addEventListener("input", (e) => {
  document.getElementById("f-hops-out").textContent = e.target.value;
  applyFilters();
});
document.getElementById("f-search").addEventListener("input", applyFilters);
document.getElementById("f-reset").addEventListener("click", () => {
  initFilters();
  applyFilters();
});

function dominantRole(roleCounts) {
  let best = null, bestN = -1;
  for (const [r, n] of Object.entries(roleCounts)) if (n > bestN) { best = r; bestN = n; }
  return best;
}

function visibleId(bodyid) {
  const n = nodeById(bodyid);
  const t = (n && n.type) || "(no type)";
  return expandedTypes.has(t) ? "n" + bodyid : "t:" + t;
}

function computeVisibleElements() {
  const typeGroups = {};
  pathwayData.nodes.forEach((n) => {
    const t = n.type || "(no type)";
    if (!typeGroups[t]) typeGroups[t] = { count: 0, roleCounts: {} };
    typeGroups[t].count++;
    const role = n.role_group || "other";
    typeGroups[t].roleCounts[role] = (typeGroups[t].roleCounts[role] || 0) + 1;
  });

  const elements = [];
  for (const [t, g] of Object.entries(typeGroups)) {
    if (expandedTypes.has(t)) {
      pathwayData.nodes
        .filter((n) => (n.type || "(no type)") === t)
        .forEach((n) => {
          elements.push({
            data: { id: "n" + n.bodyid, label: n.name || String(n.bodyid), role: n.role_group || "other", kind: "neuron", bodyid: n.bodyid },
          });
        });
    } else {
      elements.push({
        data: { id: "t:" + t, label: `${t} (${g.count})`, role: dominantRole(g.roleCounts) || "other", kind: "type", typeName: t, count: g.count },
      });
    }
  }

  // Edges are added by applyFilters() (called right after this by
  // renderPathwayGraph()), not here - aggregation must see current filters.
  return elements;
}

function renderPathwayGraph() {
  if (cy) cy.destroy();
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: computeVisibleElements(),
    style: [
      {
        selector: 'node[kind="type"]',
        style: {
          "background-color": (n) => ROLE_COLORS[n.data("role")] || ROLE_COLORS.other,
          label: "data(label)",
          "font-size": 9,
          shape: "round-rectangle",
          width: (n) => 24 + 6 * Math.sqrt(n.data("count")),
          height: (n) => 24 + 6 * Math.sqrt(n.data("count")),
          "text-valign": "center",
          "text-halign": "center",
          "text-wrap": "wrap",
          "text-max-width": "70px",
          color: "#fff",
          "text-outline-width": 1,
          "text-outline-color": "#0003",
        },
      },
      {
        selector: 'node[kind="neuron"]',
        style: {
          "background-color": (n) => ROLE_COLORS[n.data("role")] || ROLE_COLORS.other,
          label: "data(label)",
          "font-size": 7,
          shape: "ellipse",
          width: 14,
          height: 14,
          "text-valign": "bottom",
          "text-margin-y": 3,
          // theme-aware: cytoscape re-evaluates style functions, so this
          // tracks light/dark without needing to rebuild the graph.
          color: () => cssVar("--text"),
        },
      },
      {
        selector: "edge",
        style: {
          width: (e) => Math.min(8, 1 + Math.log2(1 + e.data("weight"))),
          "line-color": "#b8b8c4",
          "target-arrow-color": "#b8b8c4",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          opacity: 0.7,
        },
      },
    ],
    layout: { name: "cose", animate: false, padding: 20 },
  });

  cy.on("tap", "node", (evt) => {
    const n = evt.target;
    if (n.data("kind") === "type") {
      expandedTypes.add(n.data("typeName"));
      renderPathwayGraph();
    } else {
      lastSelectedBodyid = n.data("bodyid");
      renderNeuronDetail(n.data("bodyid"));
      updateURLState();
    }
  });

  // computeVisibleElements() only builds nodes now (edges are filter-aware,
  // added below by applyFilters()) - the constructor's own `layout` option
  // above therefore runs cose on a zero-edge graph and can't reflect
  // connectivity. Re-run layout here, once edges exist, but only on this
  // initial/structural build - applyFilters() alone (no re-layout) is what
  // every subsequent filter-only change calls.
  applyFilters();
  cy.layout({ name: "cose", animate: false, padding: 20 }).run();
}

function renderPathsTable() {
  const tbody = document.querySelector("#paths-table tbody");
  tbody.innerHTML = "";
  pathwayData.paths.forEach((p) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.path}</td><td>${p.hops}</td><td>${p.total_weight}</td><td>${p.bottleneck_weight}</td>`;
    tbody.appendChild(tr);
  });
  if (pathwayData.paths.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4">No simple paths survived the max_nodes cap for this pair. Try a higher max_nodes or max_hops.</td></tr>';
  }
}

// ---------- View 4: Neuron Detail ----------
const DETAIL_FIELDS = [
  ["bodyid", "Body ID"], ["type", "Type"], ["name", "Name"], ["superclass", "Superclass"],
  ["class", "Class"], ["subclass", "Subclass"], ["somaSide", "Soma side"], ["somaNeuromere", "Soma neuromere"],
  ["consensusNt", "Consensus NT"], ["predictedNt", "Predicted NT"], ["receptorType", "Receptor type"],
  ["entryNerve", "Entry nerve"], ["exitNerve", "Exit nerve"],
  ["flywireType", "FlyWire type"], ["mancType", "MANC type"], ["hemibrainType", "Hemibrain type"],
];

function partnerLine(bodyid, weight) {
  const n = nodeById(bodyid);
  const label = n ? `${n.name || n.type || bodyid} (${bodyid})` : String(bodyid);
  return `${label}, weight ${weight}`;
}

function clearNeuronDetail() {
  lastSelectedBodyid = null;
  document.getElementById("detail-panel").innerHTML =
    '<div class="placeholder">Click an expanded neuron to see its detail here.</div>';
  const detail = document.getElementById("detail-standalone");
  detail.textContent = "Select a neuron in the Pathway Explorer (View 3) to see its detail here.";
  detail.classList.add("placeholder");
  Plotly.purge("detail-skeleton-plot");
  document.getElementById("detail-skeleton-hint").textContent =
    "Select a neuron to see its 3D morphology here.";
}

function renderNeuronDetail(bodyid) {
  const n = nodeById(bodyid);
  if (!n) return;
  lastSelectedBodyid = bodyid;

  const upstream = pathwayData.edges
    .filter((e) => e.target === bodyid)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 8);
  const downstream = pathwayData.edges
    .filter((e) => e.source === bodyid)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 8);

  let html = `<h3>${n.name || n.type || bodyid}</h3><dl>`;
  for (const [key, label] of DETAIL_FIELDS) {
    html += `<dt>${label}</dt><dd>${n[key] ?? "-"}</dd>`;
  }
  html += `<dt>Strongest upstream partners (within this drill-down)</dt><dd>${
    upstream.length ? upstream.map((e) => partnerLine(e.source, e.weight)).join("<br>") : "none in this reduced subgraph"
  }</dd>`;
  html += `<dt>Strongest downstream partners (within this drill-down)</dt><dd>${
    downstream.length ? downstream.map((e) => partnerLine(e.target, e.weight)).join("<br>") : "none in this reduced subgraph"
  }</dd>`;
  html += "</dl>";

  document.getElementById("detail-panel").innerHTML = html;
  document.getElementById("detail-standalone").innerHTML = html;
  document.getElementById("detail-standalone").classList.remove("placeholder");
  renderSkeleton(bodyid);
}

let skeletonManifest = null;
const skeletonCache = {}; // bodyid -> already-fetched skeleton record, so theme
// toggles (refreshAllCharts) can re-theme the existing geometry instead of
// re-fetching the same JSON over the network just to change a line color.
// Shared by Neuron Detail and both Anatomy overlays - every reader must
// check for this sentinel before treating a cache hit as real geometry.
const SKELETON_FETCH_FAILED = { failed: true };
fetch("data/skeletons/manifest.json")
  .then((r) => r.json())
  .then((m) => {
    skeletonManifest = m;
    // Retry renderers that bailed out with "Loading morphology index..." while this was in flight
    if (lastSelectedBodyid) renderSkeleton(lastSelectedBodyid);
    if (positionsData) { renderAnatomy(); renderAnatomy3D(); }
    refreshCoveragePanel();
  })
  .catch(() => {
    skeletonManifest = { bodyids: [] };
    if (lastSelectedBodyid) renderSkeleton(lastSelectedBodyid);
    if (positionsData) { renderAnatomy(); renderAnatomy3D(); }
    refreshCoveragePanel();
  });

function drawSkeleton(sk) {
  const hint = document.getElementById("detail-skeleton-hint");
  const traces = [{
    type: "scatter3d",
    mode: "lines",
    x: sk.x, y: sk.y, z: sk.z,
    line: { color: cssVar("--text"), width: 2 },
    hoverinfo: "skip",
    showlegend: false,
  }];
  if (sk.soma) {
    traces.push({
      type: "scatter3d",
      mode: "markers",
      name: "soma",
      x: [sk.soma.x], y: [sk.soma.y], z: [sk.soma.z],
      marker: { size: 5, color: "#c62828" },
      hoverinfo: "name",
    });
  }
  const g = gridColor();
  const axisStyle = { gridcolor: g, zerolinecolor: g, color: cssVar("--text-dim"), backgroundcolor: "rgba(0,0,0,0)" };
  Plotly.react(
    "detail-skeleton-plot",
    traces,
    plotlyThemeLayout({
      margin: { l: 0, r: 0, t: 0, b: 0 },
      scene: {
        xaxis: Object.assign({ title: "X (nm)" }, axisStyle),
        yaxis: Object.assign({ title: "Y (nm)" }, axisStyle),
        zaxis: Object.assign({ title: "Z (nm)" }, axisStyle),
        aspectmode: "data",
      },
      showlegend: false,
    }),
    { responsive: true }
  );
  hint.textContent = sk.decimated
    ? `Morphology simplified for display: ${sk.n_points_exported.toLocaleString()} of ${sk.n_points_original.toLocaleString()} skeleton points shown (long unbranched stretches thinned; branch points always kept).`
    : `${sk.n_points_exported.toLocaleString()} skeleton points. Coordinates in nm (not the "raw" voxel units used by the Anatomy views).`;
}

function renderSkeleton(bodyid) {
  const hint = document.getElementById("detail-skeleton-hint");
  if (!skeletonManifest) {
    hint.textContent = "Loading morphology index...";
    return;
  }
  if (!skeletonManifest.bodyids.includes(bodyid)) {
    Plotly.purge("detail-skeleton-plot");
    hint.textContent = "No 3D morphology available for this neuron.";
    return;
  }
  if (skeletonCache[bodyid] === SKELETON_FETCH_FAILED) {
    Plotly.purge("detail-skeleton-plot");
    hint.textContent = "Could not load morphology for this neuron.";
    return;
  }
  if (skeletonCache[bodyid]) {
    drawSkeleton(skeletonCache[bodyid]);
    return;
  }

  hint.textContent = "Loading morphology...";
  fetch(`data/skeletons/${bodyid}.json`)
    .then((r) => r.json())
    .then((sk) => {
      if (lastSelectedBodyid !== bodyid) return; // a different neuron was picked while this was in flight
      skeletonCache[bodyid] = sk;
      drawSkeleton(sk);
    })
    .catch(() => {
      skeletonCache[bodyid] = SKELETON_FETCH_FAILED;
      if (lastSelectedBodyid !== bodyid) return;
      Plotly.purge("detail-skeleton-plot");
      hint.textContent = "Could not load morphology for this neuron.";
    });
}

// ---------- View 5: Dynamics ----------
// Renders what src/io_analysis/dynamics.py already computed (illustrative
// leaky-integrator sim, not per-neuron); no dynamics run client-side.

let dynamicsData = null;
let dynamicsTimer = null;
let dynamicsT = 0;

function traceYRange(trace) {
  // Fixed per run so the axis doesn't jump during playback - computed from
  // the actual data, not assumed as tanh's (-1,1) bound.
  let m = 0;
  for (const row of trace) for (const v of row) m = Math.max(m, Math.abs(v));
  const pad = m * 0.1 || 1;
  return [-(m + pad), m + pad];
}

function renderDynamicsFrame() {
  const stim = document.getElementById("dynamics-stimulus").value;
  const trace = dynamicsData.runs[stim]; // trace[t][layerIndex]
  const layers = dynamicsData.layers;
  const t = Math.min(dynamicsT, trace.length - 1);
  const activity = trace[t];

  document.getElementById("dynamics-t").textContent = t;

  const colors = layers.map((l) => STAGE_COLORS[dynamicsData.layer_stage[l]] || "#8a8a94");
  Plotly.react(
    "dynamics-bars",
    [{ type: "bar", x: layers, y: activity, marker: { color: colors } }],
    plotlyThemeLayout({
      margin: { l: 40, r: 10, t: 10, b: 90 },
      yaxis: { range: traceYRange(trace), title: "activity (a.u.)", gridcolor: gridColor(), zerolinecolor: gridColor() },
    }),
    { responsive: true }
  );
}

// Maps processing-layer names to IO_ROLE_COLORS's keys (names only, safe
// regardless of definition order). STAGE_COLORS alone made all 5 processing
// layers the same indistinguishable blue.
const DYNAMICS_LAYER_TO_IO_ROLE_KEY = {
  optic_lobe: "optic_processing",
  central_brain: "central_processing",
  vnc: "vnc_processing",
  ascending: "ascending",
  descending: "descending",
};
function dynamicsLineColor(name) {
  const stage = dynamicsData.layer_stage[name];
  if (stage === "processing") return IO_ROLE_COLORS[DYNAMICS_LAYER_TO_IO_ROLE_KEY[name]] || "#8a8a94";
  return STAGE_COLORS[stage] || "#8a8a94";
}

function renderDynamicsLines(stim) {
  const trace = dynamicsData.runs[stim];
  const layers = dynamicsData.layers;
  const nSteps = trace.length;
  const xs = Array.from({ length: nSteps }, (_, i) => i);

  const peakByLayer = layers.map((_, j) => Math.max(...trace.map((row) => Math.abs(row[j]))));
  const outputIdx = layers
    .map((l, j) => [l, j])
    .filter(([l]) => dynamicsData.layer_stage[l] === "output")
    .sort((a, b) => peakByLayer[b[1]] - peakByLayer[a[1]])[0];

  const processingLayers = layers
    .map((l, j) => [l, j])
    .filter(([l]) => dynamicsData.layer_stage[l] === "processing");
  const stimIdx = layers.indexOf(stim);

  const series = [[stim, stimIdx], ...processingLayers];
  if (outputIdx) series.push(outputIdx);

  const lineTraces = series.map(([name, j]) => ({
    x: xs,
    y: trace.map((row) => row[j]),
    mode: "lines",
    name: name === outputIdx?.[0] ? `${name} (strongest output)` : name,
    line: { color: dynamicsLineColor(name), width: 2 },
  }));

  Plotly.react(
    "dynamics-lines",
    lineTraces,
    plotlyThemeLayout({
      margin: { l: 40, r: 10, t: 10, b: 30 },
      legend: { orientation: "h" },
      xaxis: { title: "t", gridcolor: gridColor(), zerolinecolor: gridColor() },
      yaxis: { title: "activity", gridcolor: gridColor(), zerolinecolor: gridColor() },
    }),
    { responsive: true }
  );
}

function dynamicsStop() {
  if (dynamicsTimer) { clearInterval(dynamicsTimer); dynamicsTimer = null; }
  document.getElementById("dynamics-play").textContent = "▶ Play";
}

fetch("data/dynamics.json")
  .then((r) => r.json())
  .then((d) => {
    dynamicsData = d;
    document.getElementById("dynamics-caveat").textContent = d.caveat;

    const sel = document.getElementById("dynamics-stimulus");
    Object.keys(d.runs).forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name; opt.textContent = `stimulate: ${name}`;
      sel.appendChild(opt);
    });

    dynamicsT = 0;
    renderDynamicsFrame();
    renderDynamicsLines(sel.value);

    sel.addEventListener("change", () => {
      dynamicsStop();
      dynamicsT = 0;
      renderDynamicsFrame();
      renderDynamicsLines(sel.value);
    });

    document.getElementById("dynamics-play").addEventListener("click", () => {
      if (dynamicsTimer) { dynamicsStop(); return; }
      document.getElementById("dynamics-play").textContent = "⏸ Pause";
      dynamicsTimer = setInterval(() => {
        const nSteps = dynamicsData.runs[sel.value].length;
        dynamicsT = (dynamicsT + 1) % nSteps;
        renderDynamicsFrame();
        if (dynamicsT === nSteps - 1) dynamicsStop();
      }, 80);
    });

    document.getElementById("dynamics-reset").addEventListener("click", () => {
      dynamicsStop();
      dynamicsT = 0;
      renderDynamicsFrame();
    });
  })
  .catch(() => {
    document.getElementById("dynamics-caveat").textContent =
      "data/dynamics.json not found. Run `uv run python -m io_analysis.dynamics` first.";
    document.getElementById("dynamics-info").open = true;
  });

// ---------- View 6: Anatomy (whole connectome, real soma positions) ----------
// Every point is a neuron's actual EM-volume soma coordinate, no layout
// computed. 2D scattergl instead of scatter3d - faster at 140k points, and
// the anatomy is already legible from a single 2D projection.

const IO_ROLE_COLORS = {
  optic_processing: "#e67e22",
  central_processing: "#1565c0",
  vnc_processing: "#6a1b9a",
  ascending: "#00897b",
  descending: "#ef6c00",
  motor_output: "#c62828",
  endocrine_output: "#ad1457",
  other_efferent: "#795548",
  sensory_input: "#2e7d32",
  unknown: "#9e9e9e",
};

let positionsData = null;

// Skeletons are in nm; soma positions are in malecns's "raw" voxel units.
// Measured against 2,389 neurons with both: mean ratio 7.996 (std 0.02) - a clean 8nm voxel.
const SKELETON_NM_PER_RAW_VOXEL = 8;

function toRawVoxel(coords) {
  return coords.map((v) => (v == null ? null : v / SKELETON_NM_PER_RAW_VOXEL));
}

// Cached on the record (sk._raw) - otherwise a theme toggle's refreshAllCharts()
// would re-map the whole point array just to redraw an unchanged line color.
function ensureRawVoxelCoords(sk) {
  if (!sk._raw) sk._raw = { x: toRawVoxel(sk.x), y: toRawVoxel(sk.y), z: toRawVoxel(sk.z) };
  return sk._raw;
}

// Shared by both Anatomy views' "highlight neuron" overlay: reuses the
// same manifest/cache Neuron Detail already populates, so highlighting a
// neuron you just looked at in Detail costs no extra fetch.

function getSkeletonForOverlay(bodyid) {
  return new Promise((resolve) => {
    if (!skeletonManifest || !skeletonManifest.bodyids.includes(bodyid)) { resolve(null); return; }
    if (skeletonCache[bodyid]) { resolve(skeletonCache[bodyid]); return; }
    fetch(`data/skeletons/${bodyid}.json`)
      .then((r) => r.json())
      .then((sk) => { skeletonCache[bodyid] = sk; resolve(sk); })
      // Cache the failure too - otherwise a listed-but-unfetchable bodyid
      // (manifest/file mismatch, bad JSON, ...) retries on every rerender()
      // call below, forever, each one re-plotting the whole scattergl view.
      .catch(() => { skeletonCache[bodyid] = SKELETON_FETCH_FAILED; resolve(null); });
  });
}

// Resolves the typed bodyid against the skeleton cache, updating the status
// hint; on a cache miss, fetches and retries `rerender` once it lands.
// Returns {bodyid, x, y, z} in raw voxel units, or null.
function resolveAnatomyHighlight(inputId, statusId, rerender) {
  const status = document.getElementById(statusId);
  const bodyidStr = document.getElementById(inputId).value;
  if (!bodyidStr) { status.textContent = ""; return null; }

  const bodyid = Number(bodyidStr);
  if (!skeletonManifest) { status.textContent = "Loading morphology index..."; return null; }
  if (!skeletonManifest.bodyids.includes(bodyid)) {
    status.textContent = `No 3D morphology available for body ID ${bodyid}.`;
    return null;
  }
  const cached = skeletonCache[bodyid];
  if (cached === SKELETON_FETCH_FAILED) {
    status.textContent = `Could not load morphology for body ID ${bodyid}.`;
    return null;
  }
  if (cached) {
    status.textContent = cached.decimated
      ? `Highlighting body ID ${bodyid} (simplified: ${cached.n_points_exported.toLocaleString()} of ${cached.n_points_original.toLocaleString()} skeleton points).`
      : `Highlighting body ID ${bodyid}.`;
    return { bodyid, ...ensureRawVoxelCoords(cached) };
  }
  status.textContent = "Loading skeleton...";
  getSkeletonForOverlay(bodyid).then(() => {
    if (document.getElementById(inputId).value === bodyidStr) rerender();
  });
  return null;
}

function renderAnatomy() {
  const proj = document.getElementById("anatomy-projection").value;
  const size = Number(document.getElementById("anatomy-size").value);
  const [ka, kb] = proj.split("");
  const a = positionsData[ka], b = positionsData[kb];
  const roles = positionsData.io_role;

  // one WebGL trace per io_role so the legend also acts as a toggle
  // (click a legend entry to hide/show that population).
  const byRole = {};
  for (let i = 0; i < roles.length; i++) {
    (byRole[roles[i]] ||= []).push(i);
  }
  const traces = Object.entries(byRole).map(([role, idxs]) => ({
    type: "scattergl",
    mode: "markers",
    name: `${role} (${idxs.length})`,
    x: idxs.map((i) => a[i]),
    y: idxs.map((i) => b[i]),
    marker: { size, color: IO_ROLE_COLORS[role] || "#9e9e9e", opacity: 0.55 },
  }));

  const highlight = resolveAnatomyHighlight("anatomy-highlight", "anatomy-highlight-status", renderAnatomy);
  if (highlight) {
    traces.push({
      type: "scattergl", mode: "lines", name: `highlighted: ${highlight.bodyid}`,
      x: highlight[ka], y: highlight[kb],
      line: { color: "#e91e63", width: 2 },
      hoverinfo: "skip",
    });
  }

  Plotly.react(
    "anatomy-plot",
    traces,
    plotlyThemeLayout({
      margin: { l: 40, r: 10, t: 10, b: 40 },
      xaxis: { title: ka.toUpperCase(), scaleanchor: "y", constrain: "domain", gridcolor: gridColor(), zerolinecolor: gridColor() },
      yaxis: { title: kb.toUpperCase(), autorange: "reversed", gridcolor: gridColor(), zerolinecolor: gridColor() },
      legend: { itemsizing: "constant" },
    }),
    { responsive: true }
  );
}

// ---------- View 7: Anatomy 3D (same positions, rotatable) ----------
// scatter3d is WebGL-backed, so 140k points is tried directly; "Max points"
// below is a fallback for slower machines, not a default compromise.

function subsampleByRole(cap) {
  const roles = positionsData.io_role;
  const n = roles.length;
  if (cap >= n) return Array.from({ length: n }, (_, i) => i);
  const byRole = {};
  for (let i = 0; i < n; i++) (byRole[roles[i]] ||= []).push(i);
  const frac = cap / n;
  let out = [];
  for (const idxs of Object.values(byRole)) {
    const keep = Math.max(1, Math.round(idxs.length * frac));
    // Evenly-spaced sample of exactly `keep` points, deterministic (not
    // random) so renders are reproducible. A stride computed via floor()
    // quantizes to whole steps (1, 2, 3, ...) and can badly overshoot
    // `keep` - e.g. floor(n/keep)=1 whenever keep > n/2, which returns
    // every point instead of the requested fraction.
    for (let k = 0; k < keep; k++) out.push(idxs[Math.floor((k * idxs.length) / keep)]);
  }
  return out;
}

function renderAnatomy3D() {
  const size = Number(document.getElementById("anatomy3d-size").value);
  const cap = Number(document.getElementById("anatomy3d-cap").value);
  const idxAll = subsampleByRole(cap);
  document.getElementById("anatomy3d-cap-out").textContent = idxAll.length;

  const roles = positionsData.io_role;
  const byRole = {};
  for (const i of idxAll) (byRole[roles[i]] ||= []).push(i);

  const traces = Object.entries(byRole).map(([role, idxs]) => ({
    type: "scatter3d",
    mode: "markers",
    name: `${role} (${idxs.length})`,
    x: idxs.map((i) => positionsData.x[i]),
    y: idxs.map((i) => positionsData.y[i]),
    z: idxs.map((i) => positionsData.z[i]),
    marker: { size, color: IO_ROLE_COLORS[role] || "#9e9e9e", opacity: 0.6 },
  }));

  const highlight3d = resolveAnatomyHighlight("anatomy3d-highlight", "anatomy3d-highlight-status", renderAnatomy3D);
  if (highlight3d) {
    traces.push({
      type: "scatter3d", mode: "lines", name: `highlighted: ${highlight3d.bodyid}`,
      x: highlight3d.x, y: highlight3d.y, z: highlight3d.z,
      line: { color: "#e91e63", width: 4 },
      hoverinfo: "skip",
    });
  }

  Plotly.react(
    "anatomy3d-plot",
    traces,
    (() => {
      const g = gridColor();
      const axisStyle = { gridcolor: g, zerolinecolor: g, color: cssVar("--text-dim"), backgroundcolor: "rgba(0,0,0,0)" };
      return plotlyThemeLayout({
        margin: { l: 0, r: 0, t: 0, b: 0 },
        scene: {
          xaxis: Object.assign({ title: "X" }, axisStyle),
          yaxis: Object.assign({ title: "Y" }, axisStyle),
          zaxis: Object.assign({ title: "Z", autorange: "reversed" }, axisStyle),
          aspectmode: "data",
        },
        legend: { itemsizing: "constant" },
      });
    })(),
    { responsive: true }
  );
}

// ---------- Start Here: activation-wave animation ----------
// Real neurons at their soma X-Y positions. Each wave lights them up in the
// order of an input-fraction traversal from one sensory modality (see
// export_start_animation.py): anatomical ordering, not recorded activity.

const START_ANIM = {
  stepMs: 320,       // time between traversal layers
  jitterMs: 200,     // per-neuron spread within a layer, so layers don't strobe
  riseMs: 70,
  decayMs: 600,
  holdMs: 1300,      // quiet gap after a wave before the next one starts
  ringMs: 900,
  baseAlpha: 0.16,
};

function startAnimPulse(dt) {
  if (dt < 0) return 0;
  if (dt < START_ANIM.riseMs) return dt / START_ANIM.riseMs;
  return Math.exp(-(dt - START_ANIM.riseMs) / START_ANIM.decayMs);
}

function initStartAnimation(d) {
  const canvas = document.getElementById("start-flow-anim");
  const caption = document.getElementById("start-anim-wave");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d");
  const view = document.getElementById("view-start");
  canvas.style.aspectRatio = String(d.aspect);

  const colors = d.role.map((r) => IO_ROLE_COLORS[d.role_names[r]] || IO_ROLE_COLORS.unknown);
  // Deterministic per-neuron jitter (golden-ratio hash), stable across waves.
  const jitter = d.bodyid.map((b, i) => ((i * 0.6180339887) % 1) * START_ANIM.jitterMs);
  const accent = new Set(d.accent_bodyids);
  const waveMs = d.waves.map((w) => (w.max_layer + 1) * START_ANIM.stepMs + START_ANIM.jitterMs + START_ANIM.decayMs * 3 + START_ANIM.holdMs);
  const cycleMs = waveMs.reduce((a, b) => a + b, 0);

  let cssW = 0, cssH = 0;
  function size() {
    const dpr = window.devicePixelRatio || 1;
    cssW = canvas.clientWidth;
    cssH = canvas.clientHeight;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw(tMs, waveIdx) {
    const wave = d.waves[waveIdx];
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    const r0 = Math.max(1, cssW / 520);
    // Coordinates span 0..1000 on the wider axis; keep a margin so halos
    // and the accent ring aren't clipped at the canvas edge.
    const pad = r0 * 5;
    const px = Math.min((cssW - 2 * pad) / 1000, (cssH - 2 * pad) / (1000 / d.aspect));
    const ox = (cssW - 1000 * px) / 2, oy = (cssH - (1000 / d.aspect) * px) / 2;
    ctx.clearRect(0, 0, cssW, cssH);
    for (let i = 0; i < d.n; i++) {
      const x = ox + d.x[i] * px, y = oy + d.y[i] * px;
      const layer = wave.layer[i];
      const a = layer < 0 ? 0 : startAnimPulse(tMs - layer * START_ANIM.stepMs - jitter[i]);
      ctx.fillStyle = colors[i];
      if (a > 0.04) {
        ctx.globalAlpha = a * (dark ? 0.35 : 0.22);
        ctx.beginPath(); ctx.arc(x, y, r0 * (2 + 2.5 * a), 0, 2 * Math.PI); ctx.fill();
      }
      ctx.globalAlpha = START_ANIM.baseAlpha + (1 - START_ANIM.baseAlpha) * a;
      ctx.beginPath(); ctx.arc(x, y, r0 * (1 + 0.8 * a), 0, 2 * Math.PI); ctx.fill();
      if (accent.has(d.bodyid[i]) && layer >= 0) {
        const dt = tMs - layer * START_ANIM.stepMs - jitter[i];
        if (dt >= 0 && dt < START_ANIM.ringMs) {
          const p = dt / START_ANIM.ringMs;
          ctx.globalAlpha = 0.8 * (1 - p);
          ctx.strokeStyle = colors[i];
          ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.arc(x, y, r0 * (2 + 14 * p), 0, 2 * Math.PI); ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  function setCaption(waveIdx) {
    if (caption) caption.textContent = d.waves[waveIdx].label;
  }

  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Static frame: the vision wave caught mid-way through the brain.
  const staticT = 4 * START_ANIM.stepMs + START_ANIM.jitterMs / 2;
  size();
  window.addEventListener("resize", () => { size(); if (reduced) draw(staticT, 0); });
  if (reduced) { setCaption(0); draw(staticT, 0); return; }

  let t0 = null, shownWave = -1;
  function frame(now) {
    requestAnimationFrame(frame);
    if (!view.classList.contains("active") || document.hidden) { t0 = null; return; }
    if (canvas.clientWidth !== cssW) size();
    if (t0 === null) t0 = now - (shownWave > 0 ? waveMs.slice(0, shownWave).reduce((a, b) => a + b, 0) : 0);
    let t = (now - t0) % cycleMs, w = 0;
    while (t >= waveMs[w]) { t -= waveMs[w]; w++; }
    if (w !== shownWave) { shownWave = w; setCaption(w); }
    draw(t, w);
  }
  requestAnimationFrame(frame);
}

fetch("data/start_animation.json")
  .then((r) => r.json())
  .then(initStartAnimation)
  .catch(() => {
    const note = document.getElementById("start-anim-caption");
    if (note) note.hidden = true;
  });

fetch("data/positions.json")
  .then((r) => r.json())
  .then((d) => {
    positionsData = d;
    document.getElementById("anatomy-coverage").textContent = d.coverage_note;
    renderAnatomy();
    renderAnatomy3D();
    refreshCoveragePanel();
    document.getElementById("anatomy-projection").addEventListener("change", renderAnatomy);
    document.getElementById("anatomy-size").addEventListener("input", (e) => {
      document.getElementById("anatomy-size-out").textContent = e.target.value;
      renderAnatomy();
    });

    document.getElementById("anatomy3d-size").addEventListener("input", (e) => {
      document.getElementById("anatomy3d-size-out").textContent = e.target.value;
      renderAnatomy3D();
    });
    document.getElementById("anatomy3d-cap").addEventListener("change", renderAnatomy3D);

    document.getElementById("anatomy-highlight").addEventListener("change", renderAnatomy);
    document.getElementById("anatomy-highlight-clear").addEventListener("click", () => {
      document.getElementById("anatomy-highlight").value = "";
      renderAnatomy();
    });
    document.getElementById("anatomy3d-highlight").addEventListener("change", renderAnatomy3D);
    document.getElementById("anatomy3d-highlight-clear").addEventListener("click", () => {
      document.getElementById("anatomy3d-highlight").value = "";
      renderAnatomy3D();
    });
  })
  .catch(() => {
    document.getElementById("anatomy-coverage").textContent =
      "data/positions.json not found. Run r/build_neuron_positions.R, then `uv run python -m io_analysis.export_positions`.";
  });

// ---------- global neuron search ----------
// Searches all 165,122 traced neurons, not just the 6,895 reachable through
// a pathway drill-down - a match outside that set still shows its census
// metadata but can't open an interactive graph or 3D morphology.
let searchRows = null;
// Distinct from searchRows staying null while loading - a failed fetch
// must not be indistinguishable from "loaded, zero matches", or every
// query silently shows "No traced neuron matches" on a fresh checkout
// that hasn't run export_search_index.py yet, instead of saying so.
let searchIndexFailed = false;

// Named so applyInitialDeepLink() can await it to resolve a `?bodyid=` deep
// link with no `?pathway=`.
const searchIndexReady = fetch("data/search_index.json")
  .then((r) => r.json())
  .then((idx) => {
    const n = idx.bodyid.length;
    const rows = new Array(n);
    for (let i = 0; i < n; i++) {
      const type = idx.type[i] || "";
      const name = idx.name[i] || "";
      rows[i] = {
        bodyid: idx.bodyid[i],
        type, name,
        superclass: idx.superclass[i],
        class: idx.class[i],
        io_role: idx.io_role[i],
        input_category: idx.input_category[i],
        output_category: idx.output_category[i],
        pathway_key: idx.pathway_key[i],
        _searchText: (type + " " + name).toLowerCase(),
      };
    }
    searchRows = rows;
  })
  .catch(() => { searchIndexFailed = true; })
  .then(refreshPendingSearch);

function refreshPendingSearch() {
  if (document.getElementById("search-modal").classList.contains("open")) {
    renderSearchResults(document.getElementById("search-input").value);
  }
}

function searchMatches(query) {
  const q = query.trim().toLowerCase();
  if (!q || !searchRows) return [];
  const byBodyid = [], byType = [], bySubstring = [];
  for (const row of searchRows) {
    // Cap checked unconditionally, before classifying, so a query that
    // prefix-matches thousands of bodyids/types (e.g. a single common
    // letter) still stops scanning the 165,122-row array early instead of
    // only capping the bySubstring fallback bucket.
    if (byBodyid.length + byType.length + bySubstring.length > 300) break;
    if (String(row.bodyid).startsWith(q)) { byBodyid.push(row); continue; }
    if (row.type.toLowerCase().startsWith(q)) { byType.push(row); continue; }
    if (row._searchText.includes(q)) bySubstring.push(row);
  }
  return [...byBodyid, ...byType, ...bySubstring].slice(0, 30);
}

function categoryBadge(row) {
  if (row.io_role === "sensory_input") return row.input_category || "sensory input";
  if (["motor_output", "endocrine_output", "other_efferent"].includes(row.io_role)) return row.output_category || "output";
  return row.io_role || "unknown";
}

function renderSearchResults(query) {
  const container = document.getElementById("search-results");
  const matches = searchMatches(query);
  if (!query.trim()) {
    container.innerHTML = '<div class="search-empty">Type a cell type name or body ID to search.</div>';
    return;
  }
  if (searchIndexFailed) {
    container.innerHTML = '<div class="search-empty">data/search_index.json not found. Run `uv run python -m io_analysis.export_search_index` first.</div>';
    return;
  }
  if (!searchRows) {
    container.innerHTML = '<div class="search-empty">Loading search index...</div>';
    return;
  }
  if (matches.length === 0) {
    container.innerHTML = '<div class="search-empty">No traced neuron matches.</div>';
    return;
  }
  container.innerHTML = matches.map((row, i) => `
    <div class="search-result" data-idx="${i}" data-bodyid="${row.bodyid}">
      <span class="sr-name">${row.name || row.type || row.bodyid}</span>
      <span class="sr-bodyid">${row.bodyid}</span>
      <span class="sr-meta">${row.pathway_key ? categoryBadge(row) : `${categoryBadge(row)} <span class="sr-unreachable">(no drill-down)</span>`}</span>
    </div>
  `).join("");
  container.querySelectorAll(".search-result").forEach((el) => {
    el.addEventListener("click", () => selectSearchResult(matches[Number(el.dataset.idx)]));
  });
}

function selectSearchResult(row) {
  if (row.pathway_key) {
    const [ic, oc] = row.pathway_key.split("__");
    closeSearch();
    loadPathway(ic, oc, row.bodyid);
    return;
  }
  // Not reachable through any precomputed drill-down - show census
  // metadata inline instead of navigating anywhere, since Pathway
  // Explorer/Neuron Detail have nothing to render for this bodyid.
  const container = document.getElementById("search-results");
  container.innerHTML = `
    <div class="search-empty" style="text-align:left;">
      <button id="search-back" type="button" style="margin-bottom:8px;">&larr; Back to results</button>
      <h3 style="margin:4px 0;">${row.name || row.type || row.bodyid}</h3>
      <dl>
        <dt>Body ID</dt><dd>${row.bodyid}</dd>
        <dt>Type</dt><dd>${row.type || "-"}</dd>
        <dt>Superclass</dt><dd>${row.superclass || "-"}</dd>
        <dt>Class</dt><dd>${row.class || "-"}</dd>
        <dt>io_role</dt><dd>${row.io_role || "unknown"}</dd>
      </dl>
      <p class="hint" style="margin-top:8px;">This neuron isn't part of any precomputed pathway drill-down, so there's no interactive graph or 3D morphology available for it here - only the census metadata above.</p>
    </div>
  `;
  document.getElementById("search-back").addEventListener("click", () => {
    renderSearchResults(document.getElementById("search-input").value);
  });
}

function openSearch() {
  const modal = document.getElementById("search-modal");
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  document.querySelector("header").inert = true;
  document.querySelector("nav").inert = true;
  document.querySelector("main").inert = true;
  const input = document.getElementById("search-input");
  input.value = "";
  renderSearchResults("");
  input.focus();
}

function closeSearch() {
  const modal = document.getElementById("search-modal");
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
  // header itself must never stay inert outside of search being open, or
  // .header-controls (search-toggle, header-toggle, theme-toggle) becomes
  // permanently unclickable - only #header-body gets the collapsed-header
  // treatment, matching the header-toggle handler's own scoping.
  document.querySelector("header").inert = false;
  headerBody.inert = document.documentElement.getAttribute("data-header") === "collapsed";
  document.querySelector("nav").inert = false;
  document.querySelector("main").inert = false;
  document.getElementById("search-toggle").focus();
}

document.getElementById("search-toggle").addEventListener("click", openSearch);
document.getElementById("search-close").addEventListener("click", closeSearch);
document.getElementById("search-modal").addEventListener("click", (e) => {
  if (e.target.id === "search-modal") closeSearch(); // click on the backdrop
});
let searchDebounce = null;
document.getElementById("search-input").addEventListener("input", (e) => {
  const value = e.target.value;
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => renderSearchResults(value), 80);
});
document.getElementById("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSearch();
  if (e.key === "Enter") {
    const first = document.querySelector(".search-result");
    if (first) first.click();
  }
});
document.addEventListener("keydown", (e) => {
  const modalOpen = document.getElementById("search-modal").classList.contains("open");
  if (modalOpen && e.key === "Escape") { closeSearch(); return; }
  if (modalOpen) return;
  const tag = document.activeElement?.tagName;
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.activeElement?.isContentEditable;
  if (e.key === "/" && !typing) { e.preventDefault(); openSearch(); }
});

// Called last (not where it's defined) since a `?bodyid=` deep link with no
// `?pathway=` needs searchIndexReady, declared further up but only
// guaranteed to exist as a Promise once this point in the script is reached.
applyInitialDeepLink();
