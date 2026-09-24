#!/usr/bin/env Rscript
#
# build_neuron_skeletons.R - fetches skeleton geometry (SWC-style points +
# parent-pointer topology) via malecns::read_mcns_neurons() for the ~6,748
# bodyids reachable through Pathway Explorer (data/skeleton_bodyids.csv),
# not all 165k. Coordinates are nm, not the "raw" voxel units elsewhere.
# Batched (50/batch, retries singly on batch failure), checkpointed every
# 20 batches - full run takes about an hour. Usage: Rscript r/build_neuron_skeletons.R

fail <- function(msg, ...) stop(sprintf(msg, ...), call. = FALSE)

if (!requireNamespace("malecns", quietly = TRUE)) {
  fail("Could not load the 'malecns' package. See README.md for install instructions.")
}
suppressPackageStartupMessages(library(malecns))
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default
if (!requireNamespace("arrow", quietly = TRUE)) {
  fail("Could not load the 'arrow' package (needed to write Parquet).")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  fail("Could not load the 'jsonlite' package (needed to write the manifest).")
}

ids_path <- "data/skeleton_bodyids.csv"
if (!file.exists(ids_path)) {
  fail("%s not found - run `uv run python -m io_analysis.list_skeleton_targets` first.", ids_path)
}
ids <- utils::read.csv(ids_path, stringsAsFactors = FALSE)$bodyid
cat(sprintf("Fetching skeletons for %d bodies ...\n", length(ids)))

raw_dir <- "data/raw"
if (!dir.exists(raw_dir)) dir.create(raw_dir, recursive = TRUE)
out_path <- file.path(raw_dir, "neuron_skeletons.parquet")
manifest_path <- file.path(raw_dir, "neuron_skeletons_manifest.json")

batch_size <- 50
batches <- split(ids, ceiling(seq_along(ids) / batch_size))
n_batches <- length(batches)

fetch_one <- function(id) {
  n <- tryCatch(read_mcns_neurons(id), error = function(e) NULL)
  if (is.null(n) || length(n) == 0) return(NULL)
  d <- n[[1]]$d
  d$bodyid <- id
  d$is_soma <- seq_len(nrow(d)) == n[[1]]$soma
  d
}

all_rows <- list()
failed_ids <- integer(0)
t_start <- Sys.time()

for (i in seq_len(n_batches)) {
  batch <- batches[[i]]
  batch_result <- tryCatch(
    {
      nl <- read_mcns_neurons(batch)
      out <- vector("list", length(nl))
      fetched_ids <- as.integer(names(nl))
      for (j in seq_along(nl)) {
        d <- nl[[j]]$d
        d$bodyid <- fetched_ids[j]
        d$is_soma <- seq_len(nrow(d)) == nl[[j]]$soma
        out[[j]] <- d
      }
      list(rows = out, missing = setdiff(batch, fetched_ids))
    },
    error = function(e) {
      # whole-batch fetch failed - fall back to one-at-a-time so a single
      # bad id doesn't discard the rest of this batch
      rows <- list()
      missing <- integer(0)
      for (id in batch) {
        d <- fetch_one(id)
        if (is.null(d)) missing <- c(missing, id) else rows[[length(rows) + 1]] <- d
      }
      list(rows = rows, missing = missing)
    }
  )
  all_rows <- c(all_rows, batch_result$rows)
  failed_ids <- c(failed_ids, batch_result$missing)

  if (i %% 10 == 0 || i == n_batches) {
    elapsed <- as.numeric(Sys.time() - t_start, units = "secs")
    cat(sprintf(
      "  batch %d/%d - %d neurons fetched so far, %d failed (%.0fs elapsed)\n",
      i, n_batches, length(all_rows), length(failed_ids), elapsed
    ))
  }

  if (i %% 20 == 0 || i == n_batches) {
    if (length(all_rows) == 0) {
      fail("Every batch so far has failed (0/%d neurons fetched) - stopping instead of writing an empty Parquet file. Check neuPrint connectivity/token.", i * batch_size)
    }
    checkpoint <- do.call(rbind, all_rows)
    arrow::write_parquet(checkpoint, out_path, compression = "zstd")
  }
}

if (length(all_rows) == 0) {
  fail("Fetched 0/%d neurons - nothing to save.", length(ids))
}
skeletons <- do.call(rbind, all_rows)
arrow::write_parquet(skeletons, out_path, compression = "zstd")
file_size_bytes <- file.size(out_path)

cat(sprintf(
  "\nDone: %d/%d neurons, %d points total, %d failed.\nSaved -> %s (%.1f MB, zstd)\n",
  length(all_rows), length(ids), nrow(skeletons), length(failed_ids), out_path, file_size_bytes / 1024^2
))

manifest <- list(
  dataset = "male-cns:v1.0",
  extraction_timestamp_utc = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  source_function = "malecns::read_mcns_neurons(ids)",
  units = "nm",
  n_requested = length(ids),
  n_fetched = length(all_rows),
  n_failed = length(failed_ids),
  failed_bodyids = as.character(failed_ids),
  total_points = nrow(skeletons),
  batch_size = batch_size,
  elapsed_seconds = round(as.numeric(Sys.time() - t_start, units = "secs"), 1),
  file_path = out_path,
  file_size_bytes = file_size_bytes
)
jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("Manifest -> %s\n", manifest_path))
