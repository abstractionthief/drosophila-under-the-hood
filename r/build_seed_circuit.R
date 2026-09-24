#!/usr/bin/env Rscript
#
# build_seed_circuit.R - deterministic node/edge dataset around seed neuron
# 10039 (VL2a_adPN_R). Retrieves, validates, and saves; no thresholding or
# simulation. Usage: Rscript r/build_seed_circuit.R

seed_bodyid <- 10039L

fail <- function(msg, ...) {
  stop(sprintf(msg, ...), call. = FALSE)
}

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail("Could not load the 'malecns' package. See README.md for install instructions.")
}
suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

conn_in <- tryCatch(
  mcns_connection_table(seed_bodyid, partners = "inputs", moredetails = FALSE),
  error = function(e) {
    fail("mcns_connection_table(%s, partners='inputs') failed: %s", seed_bodyid, conditionMessage(e))
  }
)
conn_out <- tryCatch(
  mcns_connection_table(seed_bodyid, partners = "outputs", moredetails = FALSE),
  error = function(e) {
    fail("mcns_connection_table(%s, partners='outputs') failed: %s", seed_bodyid, conditionMessage(e))
  }
)

for (nm in c("conn_in", "conn_out")) {
  df <- get(nm)
  if (!is.data.frame(df) || !all(c("bodyid", "partner", "prepost", "weight") %in% colnames(df))) {
    fail("%s is missing expected columns (bodyid, partner, prepost, weight).", nm)
  }
}

cat(sprintf("Seed neuron: bodyid %d\n", seed_bodyid))
cat(sprintf("Upstream (input) connections retrieved: %d\n", nrow(conn_in)))
cat(sprintf("Downstream (output) connections retrieved: %d\n", nrow(conn_out)))

summarize_weights <- function(w, label) {
  cat(sprintf("\n%s weight distribution:\n", label))
  if (length(w) == 0) {
    cat("  (no connections)\n")
    return(invisible(NULL))
  }
  q <- stats::quantile(w, probs = c(0.75, 0.90, 0.95, 0.99), names = FALSE, type = 7)
  stats_df <- data.frame(
    n      = length(w),
    min    = min(w),
    median = stats::median(w),
    mean   = mean(w),
    p75    = q[1],
    p90    = q[2],
    p95    = q[3],
    p99    = q[4],
    max    = max(w)
  )
  print(stats_df, row.names = FALSE)
  invisible(stats_df)
}

summarize_weights(conn_in$weight, "Upstream (input)")
summarize_weights(conn_out$weight, "Downstream (output)")

partner_ids <- unique(c(conn_in$partner, conn_out$partner))
all_ids <- unique(c(seed_bodyid, partner_ids))

meta <- tryCatch(
  mcns_neuprint_meta(all_ids),
  error = function(e) {
    fail("mcns_neuprint_meta() failed for %d ids: %s", length(all_ids), conditionMessage(e))
  }
)
if (!is.data.frame(meta) || nrow(meta) == 0) {
  fail("mcns_neuprint_meta() returned no metadata for the seed + partner ids.")
}

bio_cols <- c(
  "bodyid", "type", "name", "class", "superclass", "somaSide",
  "consensusNt", "predictedNt", "receptorType",
  "flywireType", "mancType", "hemibrainType"
)
bio_cols_present <- intersect(bio_cols, colnames(meta))
bio_cols_missing <- setdiff(bio_cols, bio_cols_present)
if (length(bio_cols_missing) > 0) {
  cat(sprintf(
    "\n(Metadata columns not present in this dataset, skipped: %s)\n",
    paste(bio_cols_missing, collapse = ", ")
  ))
}

nodes <- meta[, bio_cols_present, drop = FALSE]
nodes$bodyid <- as.numeric(nodes$bodyid)
nodes <- nodes[!duplicated(nodes$bodyid), , drop = FALSE]

missing_ids <- setdiff(all_ids, nodes$bodyid)
if (length(missing_ids) > 0) {
  fail(
    "mcns_neuprint_meta() did not return metadata for %d id(s): %s",
    length(missing_ids), paste(head(missing_ids, 10), collapse = ", ")
  )
}

# prepost==0 (upstream partner): partner->seed; prepost==1: seed->partner
combined <- rbind(
  conn_in[, c("bodyid", "partner", "prepost", "weight")],
  conn_out[, c("bodyid", "partner", "prepost", "weight")]
)

if (!all(combined$prepost %in% c(0, 1))) {
  fail("Unexpected 'prepost' value(s) other than 0/1 in connection table(s).")
}
if (any(combined$bodyid != seed_bodyid)) {
  fail("Connection table contains rows not anchored on the seed bodyid.")
}

edges <- data.frame(
  source = ifelse(combined$prepost == 0, combined$partner, seed_bodyid),
  target = ifelse(combined$prepost == 0, seed_bodyid, combined$partner),
  weight = combined$weight
)
edges$source <- as.numeric(edges$source)
edges$target <- as.numeric(edges$target)

node_ids <- nodes$bodyid

bad_source <- setdiff(unique(edges$source), node_ids)
bad_target <- setdiff(unique(edges$target), node_ids)
if (length(bad_source) > 0 || length(bad_target) > 0) {
  fail(
    "Edge endpoints missing from node table: sources=%s targets=%s",
    paste(bad_source, collapse = ","), paste(bad_target, collapse = ",")
  )
}

if (any(is.na(edges$weight)) || any(edges$weight <= 0)) {
  fail("Found non-positive or NA edge weight(s).")
}

edge_key <- paste(edges$source, edges$target, sep = "->")
dup_keys <- edge_key[duplicated(edge_key)]
if (length(dup_keys) > 0) {
  fail("Found %d duplicate directed edge(s): %s", length(dup_keys), paste(unique(dup_keys), collapse = ", "))
}

seed_count <- sum(node_ids == seed_bodyid)
if (seed_count != 1) {
  fail("Expected the seed neuron to appear exactly once in the node table, found %d.", seed_count)
}

cat("\nValidation passed: edge endpoints in node table, weights positive, no duplicate edges, seed present exactly once.\n")

cat(sprintf("\nUnique nodes: %d\n", nrow(nodes)))
cat(sprintf("Directed edges: %d\n", nrow(edges)))

fmt_pct <- function(n, total) sprintf("%d (%.1f%%)", n, 100 * n / total)

cat("\nNeurotransmitter value counts (consensusNt):\n")
if ("consensusNt" %in% colnames(nodes)) {
  print(table(nodes$consensusNt, useNA = "ifany"))
} else {
  cat("  (consensusNt column not available)\n")
}

cat("\nSuperclass value counts:\n")
if ("superclass" %in% colnames(nodes)) {
  print(table(nodes$superclass, useNA = "ifany"))
} else {
  cat("  (superclass column not available)\n")
}

n_total <- nrow(nodes)
if ("consensusNt" %in% colnames(nodes)) {
  n_missing_nt <- sum(is.na(nodes$consensusNt))
  cat(sprintf("\nNodes missing consensusNt: %s\n", fmt_pct(n_missing_nt, n_total)))
} else {
  cat("\nNodes missing consensusNt: column not available\n")
}

if ("receptorType" %in% colnames(nodes)) {
  n_missing_rt <- sum(is.na(nodes$receptorType))
  cat(sprintf("Nodes missing receptorType: %s\n", fmt_pct(n_missing_rt, n_total)))
} else {
  cat("Nodes missing receptorType: column not available\n")
}

data_dir <- "data"
if (!dir.exists(data_dir)) {
  dir.create(data_dir, recursive = TRUE)
}

nodes_path <- file.path(data_dir, "seed_10039_nodes.csv")
edges_path <- file.path(data_dir, "seed_10039_edges.csv")

utils::write.csv(nodes, nodes_path, row.names = FALSE)
utils::write.csv(edges, edges_path, row.names = FALSE)

cat(sprintf("\nSaved nodes -> %s (%d rows)\n", nodes_path, nrow(nodes)))
cat(sprintf("Saved edges -> %s (%d rows)\n", edges_path, nrow(edges)))

cat("\nDone.\n")
