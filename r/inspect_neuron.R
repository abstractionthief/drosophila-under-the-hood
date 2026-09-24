#!/usr/bin/env Rscript
#
# inspect_neuron.R - print what malecns/neuPrint actually return for one
# neuron (metadata + connectivity) before designing anything on top of it.
# Usage: Rscript r/inspect_neuron.R

fail <- function(msg, ...) {
  stop(sprintf(msg, ...), call. = FALSE)
}

print_small <- function(df, n = 10, cols = NULL) {
  if (!is.null(cols)) {
    cols <- intersect(cols, colnames(df))
    df <- df[, cols, drop = FALSE]
  }
  print(utils::head(df, n))
}

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail("Could not load the 'malecns' package. See README.md for install instructions.")
}
suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

query <- "/.+_[adl]+PN"

pnmeta <- tryCatch(
  mcns_neuprint_meta(query),
  error = function(e) {
    fail("mcns_neuprint_meta('%s') failed: %s", query, conditionMessage(e))
  }
)

if (!is.data.frame(pnmeta) || nrow(pnmeta) == 0) {
  fail("mcns_neuprint_meta('%s') returned no rows - nothing to inspect.", query)
}

cat(sprintf("Projection-neuron query: %s (%d rows)\n", query, nrow(pnmeta)))
cat("\nMetadata columns:\n")
print(colnames(pnmeta))

if (!"bodyid" %in% colnames(pnmeta)) {
  fail("Expected a 'bodyid' column in the metadata but didn't find one.")
}

# lowest bodyid, not sample() - reproducible run to run
pnmeta <- pnmeta[order(pnmeta$bodyid), ]
neuron <- pnmeta[1, ]
bodyid <- neuron$bodyid

cat(sprintf("\nSelected neuron (lowest bodyid, deterministic): %s\n", bodyid))

bio_cols <- c(
  "bodyid", "type", "instance", "name",
  "class", "superclass", "somaSide", "group",
  "consensusNt", "predictedNt", "celltypePredictedNt",
  "flywireType", "mancType", "hemibrainType"
)
bio_cols_present <- intersect(bio_cols, colnames(pnmeta))

cat("Available biological metadata for this neuron:\n")
print(as.list(neuron[, bio_cols_present, drop = FALSE]))

missing_bio <- setdiff(
  c("consensusNt", "predictedNt", "celltypePredictedNt", "flywireType", "mancType"),
  bio_cols_present
)
if (length(missing_bio) > 0) {
  cat(sprintf(
    "\n(Not present for this dataset/neuron: %s)\n",
    paste(missing_bio, collapse = ", ")
  ))
}

# mcns_connection_table() wraps neuprint_connection_table(details=TRUE) and
# left-joins meta columns onto each partner; we re-sort by weight explicitly
# rather than trust the wrapper's internal ordering.
conn_in <- tryCatch(
  mcns_connection_table(bodyid, partners = "inputs"),
  error = function(e) {
    fail("mcns_connection_table(%s, partners='inputs') failed: %s", bodyid, conditionMessage(e))
  }
)

conn_out <- tryCatch(
  mcns_connection_table(bodyid, partners = "outputs"),
  error = function(e) {
    fail("mcns_connection_table(%s, partners='outputs') failed: %s", bodyid, conditionMessage(e))
  }
)

if (!is.data.frame(conn_in) || !is.data.frame(conn_out)) {
  fail("mcns_connection_table() did not return data.frames for bodyid %s.", bodyid)
}

cat("\nConnectivity table columns (inputs):\n")
print(colnames(conn_in))
cat("\nConnectivity table columns (outputs):\n")
print(colnames(conn_out))

if (!"weight" %in% colnames(conn_in) || !"weight" %in% colnames(conn_out)) {
  fail("Expected a 'weight' column in the connectivity tables but didn't find one.")
}

partner_cols <- c("partner", "weight", "type", "instance", "name", "superclass", "somaSide", "group")

if (nrow(conn_in) == 0) {
  cat("\nNo upstream (input) partners found for this neuron.\n")
} else {
  conn_in <- conn_in[order(conn_in$weight, decreasing = TRUE), ]
  cat(sprintf("\nStrongest upstream partners (of %d total):\n", nrow(conn_in)))
  print_small(conn_in, n = 10, cols = partner_cols)
}

if (nrow(conn_out) == 0) {
  cat("\nNo downstream (output) partners found for this neuron.\n")
} else {
  conn_out <- conn_out[order(conn_out$weight, decreasing = TRUE), ]
  cat(sprintf("\nStrongest downstream partners (of %d total):\n", nrow(conn_out)))
  print_small(conn_out, n = 10, cols = partner_cols)
}

cat("\nDone.\n")
