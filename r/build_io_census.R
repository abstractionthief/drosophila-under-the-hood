#!/usr/bin/env Rscript
#
# build_io_census.R - Phase 1: retrieve metadata for every body in MaleCNS,
# save a normalized raw node table, and report summary stats to design
# classification rules (Phase 2, docs/io_classification_rules.md) on real
# data. Does not classify anything. Usage: Rscript r/build_io_census.R

fail <- function(msg, ...) {
  stop(sprintf(msg, ...), call. = FALSE)
}

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail("Could not load the 'malecns' package. See README.md for install instructions.")
}
suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

extraction_time <- format(Sys.time(), tz = "UTC", usetz = TRUE)

cat("Fetching full MaleCNS census via mcns_neuprint_meta() ...\n")
t0 <- Sys.time()
census <- tryCatch(
  mcns_neuprint_meta(),
  error = function(e) fail("mcns_neuprint_meta() failed: %s", conditionMessage(e))
)
elapsed <- as.numeric(Sys.time() - t0, units = "secs")

if (!is.data.frame(census) || nrow(census) == 0) {
  fail("mcns_neuprint_meta() returned no rows.")
}
cat(sprintf("Retrieved %d rows in %.1fs.\n", nrow(census), elapsed))

# mcns_neuprint_meta() with no ids returns EVERY DVID-annotated body (glia,
# orphans, fragments too), not just traced neurons - hence status below.
required_cols <- c(
  "bodyid", "type", "name", "superclass", "class", "subclass",
  "somaSide", "somaNeuromere", "entryNerve", "exitNerve", "receptorType",
  "consensusNt", "predictedNt", "celltypePredictedNt",
  "flywireType", "mancType", "hemibrainType", "group", "rootSide", "dimorphism"
)
provenance_cols <- c("status", "statusLabel")

missing_required <- setdiff(required_cols, colnames(census))
if (length(missing_required) > 0) {
  fail("Expected column(s) not present in mcns_neuprint_meta() output: %s",
       paste(missing_required, collapse = ", "))
}
missing_provenance <- setdiff(provenance_cols, colnames(census))
if (length(missing_provenance) > 0) {
  # status filters every downstream script (classification.py, graph.py, ...)
  # - fail here, at the point of absence, not three files removed from it.
  fail("Expected provenance column(s) not present in mcns_neuprint_meta() output: %s",
       paste(missing_provenance, collapse = ", "))
}
provenance_cols <- intersect(provenance_cols, colnames(census))

nodes <- census[, c(required_cols, provenance_cols), drop = FALSE]
nodes$bodyid <- as.numeric(nodes$bodyid)

if (any(duplicated(nodes$bodyid))) {
  fail("Duplicate bodyid(s) found in census - expected one row per body.")
}

data_dir <- "data"
if (!dir.exists(data_dir)) dir.create(data_dir, recursive = TRUE)
nodes_path <- file.path(data_dir, "io_census_nodes.csv")
# avoid scientific notation (e.g. 1e+05) - forces downstream readers to
# infer Float64 for an integer id column, needing a cast at every join
old_scipen <- options(scipen = 999)
utils::write.csv(nodes, nodes_path, row.names = FALSE)
options(old_scipen)
cat(sprintf("Saved -> %s (%d rows, %d cols)\n", nodes_path, nrow(nodes), ncol(nodes)))

fmt_pct <- function(n, total) sprintf("%d (%.1f%%)", n, 100 * n / total)

count_table <- function(x, useNA = "ifany") {
  sort(table(x, useNA = useNA), decreasing = TRUE)
}

capture_print <- function(x) {
  paste(utils::capture.output(print(x)), collapse = "\n")
}

n_total <- nrow(nodes)
report <- character(0)
add <- function(...) report <<- c(report, sprintf(...))
add_block <- function(txt) report <<- c(report, txt)

add("MaleCNS I/O census report")
add("==========================")
add("dataset: male-cns:v1.0")
add("extraction_timestamp_utc: %s", extraction_time)
add("fetch_elapsed_seconds: %.1f", elapsed)
add("")

add("Total rows in raw census (all DVID-annotated bodies): %d", n_total)
if ("status" %in% colnames(nodes)) {
  status_tbl <- count_table(nodes$status)
  traced_n <- sum(nodes$status == "Traced", na.rm = TRUE)
  add("Rows with status == 'Traced' (closest match to \"neuron\"): %s", fmt_pct(traced_n, n_total))
  add("")
  add("Status breakdown (all rows):")
  add_block(capture_print(status_tbl))
  add("")
} else {
  add("(status column unavailable - cannot separate traced neurons from glia/orphans/fragments)")
  add("")
}

add("Superclass value counts (all %d rows):", n_total)
add_block(capture_print(count_table(nodes$superclass)))
add("")

add("Class value counts, top 40 (all %d rows):", n_total)
add_block(capture_print(utils::head(count_table(nodes$class), 40)))
add("")

sensory_superclasses <- c(
  "cb_sensory", "ol_sensory", "vnc_sensory",
  "sensory_ascending", "sensory_descending",
  "cb_sensory_tbc", "vnc_sensory_tbc", "sensory_ascending_tbc"
)
output_superclasses <- c(
  "vnc_motor", "cb_motor", "vnc_endocrine", "cb_endocrine",
  "vnc_efferent", "cb_efferent", "efferent_ascending", "efferent_descending"
)

is_sensory_sc <- nodes$superclass %in% sensory_superclasses
is_output_sc <- nodes$superclass %in% output_superclasses

add("Class values among sensory-superclass rows (n=%d):", sum(is_sensory_sc))
add_block(capture_print(count_table(nodes$class[is_sensory_sc])))
add("")

add("Class values among output-superclass rows (n=%d) - see discrepancy note below:", sum(is_output_sc))
add_block(capture_print(count_table(nodes$class[is_output_sc])))
add("")

add("Subclass value counts, top 40 (all %d rows):", n_total)
add_block(capture_print(utils::head(count_table(nodes$subclass), 40)))
add("")

add("Subclass values among sensory-superclass rows, top 30 (n=%d):", sum(is_sensory_sc))
add_block(capture_print(utils::head(count_table(nodes$subclass[is_sensory_sc]), 30)))
add("")

add("entryNerve value counts (all %d rows):", n_total)
add_block(capture_print(count_table(nodes$entryNerve)))
add("")

add("exitNerve value counts (all %d rows):", n_total)
add_block(capture_print(count_table(nodes$exitNerve)))
add("")

add("somaNeuromere value counts (all %d rows):", n_total)
add_block(capture_print(count_table(nodes$somaNeuromere)))
add("")

rt_present <- !is.na(nodes$receptorType) & nzchar(as.character(nodes$receptorType))
add("receptorType coverage: %s non-missing", fmt_pct(sum(rt_present), n_total))
add("receptorType top values (non-missing only):")
add_block(capture_print(utils::head(count_table(nodes$receptorType[rt_present], useNA = "no"), 20)))
add("")

for (nt_col in c("consensusNt", "predictedNt", "celltypePredictedNt")) {
  nt_missing <- sum(is.na(nodes[[nt_col]]))
  add("%s coverage: %s non-missing", nt_col, fmt_pct(n_total - nt_missing, n_total))
  add_block(capture_print(count_table(nodes[[nt_col]])))
  add("")
}

add("Missing-value percentage per retained field:")
miss_lines <- vapply(required_cols, function(col) {
  n_miss <- sum(is.na(nodes[[col]]) | (is.character(nodes[[col]]) & !nzchar(nodes[[col]])))
  sprintf("  %-22s %s", col, fmt_pct(n_miss, n_total))
}, character(1))
add_block(paste(miss_lines, collapse = "\n"))
add("")

# Provisional io_role tally, superclass-only (the one near-complete field).
# Report-only, not saved to the node CSV - Phase 2 implements the real
# io_role/input_category/output_category columns on a separate derived table.
tbc_suffixed <- grepl("_tbc$", nodes$superclass)

role <- ifelse(
  is.na(nodes$superclass) | tbc_suffixed | nodes$superclass == "ENS",
  "unknown",
  ifelse(nodes$superclass %in% sensory_superclasses, "sensory_input",
  ifelse(nodes$superclass %in% c("vnc_motor", "cb_motor"), "motor_output",
  ifelse(nodes$superclass %in% c("vnc_endocrine", "cb_endocrine"), "endocrine_output",
  ifelse(nodes$superclass %in% c("vnc_efferent", "cb_efferent", "efferent_ascending", "efferent_descending"), "other_efferent",
  ifelse(nodes$superclass %in% c("ol_intrinsic", "visual_projection", "visual_centrifugal"), "optic_processing",
  ifelse(nodes$superclass == "cb_intrinsic", "central_processing",
  ifelse(nodes$superclass == "vnc_intrinsic", "vnc_processing",
  ifelse(nodes$superclass == "ascending_neuron", "ascending",
  ifelse(nodes$superclass == "descending_neuron", "descending",
  "unknown"
))))))))))

input_n <- sum(role == "sensory_input")
output_n <- sum(role %in% c("motor_output", "endocrine_output", "other_efferent"))
unknown_n <- sum(role == "unknown")

add("Tentative io_role tally (superclass-based only, PROVISIONAL - see docs/io_classification_rules.md):")
add("  input  (sensory_input):                          %s", fmt_pct(input_n, n_total))
add("  output (motor_output+endocrine_output+other_efferent): %s", fmt_pct(output_n, n_total))
add("  unknown (no superclass, '_tbc', or ENS):          %s", fmt_pct(unknown_n, n_total))
add("  full role breakdown:")
add_block(capture_print(count_table(role, useNA = "no")))
add("")

add("Discrepancies vs. initial conceptual categories:")
add("  1. \"~166k neurons\" matches status == 'Traced' (%d), NOT the raw census", traced_n)
add("     row count (%d). The raw census also includes Glia, Orphan, Assign,", n_total)
add("     Anchor, and Unimportant bodies, almost none of which have a superclass.")
add("  2. `class` is essentially unusable for output classification: among the")
add("     %d rows with a motor/endocrine/efferent superclass, `class` is NA for", sum(is_output_sc))
add("     %d of them (100%%). Deriving output_category will require exitNerve /", sum(is.na(nodes$class[is_output_sc])))
add("     somaNeuromere / type-name patterns instead, per docs/io_classification_rules.md.")
add("  3. `receptorType` covers only %s of all rows - far too sparse to use as a", fmt_pct(sum(rt_present), n_total))
add("     general classification field; useful only for specific OSN drill-downs.")
add("  4. Several superclasses carry an explicit '_tbc' (to-be-confirmed) suffix")
add("     in the dataset itself; these are treated as unknown rather than forced")
add("     into a role, honoring the dataset's own uncertainty rather than ours.")
add("  5. The candidate input_category 'auditory_antennal' has no direct match in")
add("     `class`; only `subclass` hints exist (e.g. 'auditory', 'wind_gravity',")
add("     'chordotonal organ') and will need dedicated subclass-level rules.")
add("  6. exitNerve -> body-part mapping (leg/wing/haltere/etc.) is not provided")
add("     by any MaleCNS field or package dataset inspected so far; any such")
add("     mapping relies on external published MANC nerve nomenclature and must")
add("     be flagged lower-confidence until cross-checked against the primary")
add("     literature (see docs/io_classification_rules.md).")
add("")

results_dir <- "results"
if (!dir.exists(results_dir)) dir.create(results_dir, recursive = TRUE)
report_path <- file.path(results_dir, "io_census_report.txt")
writeLines(report, report_path)

cat(sprintf("\nSaved report -> %s\n", report_path))
cat("\n--- Report contents ---\n\n")
cat(paste(report, collapse = "\n"))
cat("\n")
