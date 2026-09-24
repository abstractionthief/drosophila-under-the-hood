#!/usr/bin/env Rscript
#
# smoke_test.R - minimal pipeline check: R -> malecns -> neuPrint.
# Requires NEUPRINT_TOKEN set (e.g. in ~/.Renviron). Usage: Rscript r/smoke_test.R

fail <- function(msg, ...) {
  stop(sprintf(msg, ...), call. = FALSE)
}

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail(paste(
    "Could not load the 'malecns' package.",
    "Install it first - see README.md for instructions.",
    sep = "\n"
  ))
}

suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

query <- "/.+_[adl]+PN"

pnmeta <- tryCatch(
  mcns_neuprint_meta(query),
  error = function(e) {
    fail(paste(
      "mcns_neuprint_meta() failed while querying '%s'.",
      "",
      "This usually means neuPrint authentication or connectivity is not",
      "configured correctly. Check that:",
      "  - NEUPRINT_TOKEN is set (e.g. in ~/.Renviron)",
      "  - you have network access to https://neuprint.janelia.org",
      "  - malecns/malevnc are installed and up to date",
      "",
      "Original error:",
      "%s",
      sep = "\n"
    ), query, conditionMessage(e))
  }
)

if (is.null(pnmeta) || !is.data.frame(pnmeta)) {
  fail("mcns_neuprint_meta('%s') did not return a data.frame.", query)
}

if (nrow(pnmeta) == 0) {
  fail(paste(
    "mcns_neuprint_meta('%s') returned 0 rows.",
    "The query ran, but no matching neurons were found - check the query",
    "string and your neuPrint dataset/version configuration.",
    sep = "\n"
  ), query)
}

cat(sprintf("Query: %s\n", query))
cat(sprintf("Rows returned: %d\n", nrow(pnmeta)))

useful_cols <- intersect(
  c("bodyid", "type", "name", "instance", "somaSide", "group"),
  colnames(pnmeta)
)

if (length(useful_cols) == 0) {
  # fall back to first 5 columns if the expected ones aren't present
  useful_cols <- colnames(pnmeta)[seq_len(min(5, ncol(pnmeta)))]
}

cat("\nSample of results:\n")
print(utils::head(pnmeta[, useful_cols, drop = FALSE], 10))

cat("\nSmoke test passed.\n")
