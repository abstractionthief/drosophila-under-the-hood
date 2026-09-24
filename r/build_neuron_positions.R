#!/usr/bin/env Rscript
#
# build_neuron_positions.R - fetches soma XYZ for every bodyid in
# data/io_census_nodes.csv (additive, doesn't touch the census pipeline).
# Real positions instead of a force-directed layout of 165k nodes.
# Usage: Rscript r/build_neuron_positions.R

fail <- function(msg, ...) stop(sprintf(msg, ...), call. = FALSE)

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail("Could not load the 'malecns' package. See README.md for install instructions.")
}
suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

nodes_path <- "data/io_census_nodes.csv"
if (!file.exists(nodes_path)) {
  fail("%s not found - run r/build_io_census.R first.", nodes_path)
}
nodes <- utils::read.csv(nodes_path, stringsAsFactors = FALSE)
traced_ids <- nodes$bodyid[!is.na(nodes$status) & nodes$status == "Traced"]
cat(sprintf("Fetching soma position for %d traced bodies ...\n", length(traced_ids)))

t0 <- Sys.time()
meta <- mcns_neuprint_meta(traced_ids, simplify.xyz = FALSE)
cat(sprintf("Retrieved in %.1fs.\n", as.numeric(Sys.time() - t0, units = "secs")))

if (!"somaLocation" %in% colnames(meta)) {
  fail("mcns_neuprint_meta() did not return a somaLocation column.")
}

has_loc <- !is.na(meta$somaLocation) & nzchar(meta$somaLocation)
cat(sprintf("Bodies with a non-empty somaLocation: %d / %d (%.1f%%)\n",
            sum(has_loc), nrow(meta), 100 * sum(has_loc) / nrow(meta)))

parts <- strsplit(meta$somaLocation[has_loc], ",", fixed = TRUE)

# rbind() silently *recycles* vectors that aren't length 3 instead of
# erroring, misaligning x/y/z - check length first, drop malformed rows.
lengths_ok <- lengths(parts) == 3
if (any(!lengths_ok)) {
  cat(sprintf(
    "Dropping %d bodies with a malformed somaLocation (not exactly 3 comma-separated fields).\n",
    sum(!lengths_ok)
  ))
}

bodyid_ok <- meta$bodyid[has_loc][lengths_ok]
xyz <- do.call(rbind, lapply(parts[lengths_ok], function(p) as.numeric(trimws(p))))

positions <- data.frame(
  bodyid = as.numeric(bodyid_ok),
  x = xyz[, 1], y = xyz[, 2], z = xyz[, 3]
)

out_path <- "data/io_neuron_positions.csv"
old_scipen <- options(scipen = 999)
utils::write.csv(positions, out_path, row.names = FALSE)
options(old_scipen)

cat(sprintf("Saved -> %s (%d rows)\n", out_path, nrow(positions)))
