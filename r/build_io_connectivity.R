#!/usr/bin/env Rscript
#
# build_io_connectivity.R - Phase 3: neuron-to-neuron connectivity for every
# Traced body (data/io_census_nodes.csv), batched by source bodyid (~25.5M
# edges is too large for one query or the default adjacency-matrix chunking).
# Cypher literals must use single quotes - double quotes break the JSON
# request body. Saved as Parquet (zstd) under data/raw/, gitignored.
# Usage: Rscript r/build_io_connectivity.R

fail <- function(msg, ...) {
  stop(sprintf(msg, ...), call. = FALSE)
}

for (pkg in c("malecns", "arrow", "jsonlite", "dplyr")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    fail("Could not load the '%s' package. Install it first.", pkg)
  }
}
suppressPackageStartupMessages({
  library(malecns)
})
options(malecns.dataset = "male-cns:v1.0")  # pinned, not just the package default

extraction_time <- format(Sys.time(), tz = "UTC", usetz = TRUE)
t_start <- Sys.time()

nodes_path <- "data/io_census_nodes.csv"
if (!file.exists(nodes_path)) {
  fail("%s not found - run r/build_io_census.R first.", nodes_path)
}
nodes <- utils::read.csv(nodes_path, stringsAsFactors = FALSE)
if (!all(c("bodyid", "status") %in% colnames(nodes))) {
  fail("%s is missing expected columns (bodyid, status).", nodes_path)
}

all_node_ids <- as.numeric(nodes$bodyid)
traced_ids <- nodes$bodyid[!is.na(nodes$status) & nodes$status == "Traced"]
traced_ids <- as.numeric(traced_ids)

if (length(traced_ids) == 0) {
  fail("No rows with status == 'Traced' found in %s.", nodes_path)
}
cat(sprintf("Traced bodies to query: %d\n", length(traced_ids)))

batch_size <- 1000L
conn <- mcns_neuprint()
batches <- split(traced_ids, ceiling(seq_along(traced_ids) / batch_size))
n_batches <- length(batches)

fetch_batch <- function(ids, max_attempts = 3) {
  id_json <- paste0("[", paste(format(ids, scientific = FALSE, trim = TRUE), collapse = ","), "]")
  cypher <- sprintf(
    "MATCH (n:Neuron)-[c:ConnectsTo]->(m:Neuron) WHERE n.bodyId IN %s AND m.status = 'Traced' RETURN n.bodyId AS source, m.bodyId AS target, c.weight AS weight",
    id_json
  )
  last_err <- NULL
  for (attempt in seq_len(max_attempts)) {
    res <- tryCatch(
      with_mcns(neuprintr::neuprint_fetch_custom(cypher = cypher, conn = conn)),
      error = function(e) e
    )
    if (!inherits(res, "error")) {
      df <- neuprintr::neuprint_list2df(res, return_empty_df = TRUE)
      if (nrow(df) == 0) {
        return(data.frame(source = numeric(0), target = numeric(0), weight = numeric(0)))
      }
      return(data.frame(
        source = as.numeric(df$source),
        target = as.numeric(df$target),
        weight = as.numeric(df$weight)
      ))
    }
    last_err <- res
    Sys.sleep(2 * attempt)
  }
  fail("Batch fetch failed after %d attempts: %s", max_attempts, conditionMessage(last_err))
}

cat(sprintf("Fetching connectivity in %d batches of up to %d ids ...\n", n_batches, batch_size))
chunks <- vector("list", n_batches)
t_fetch0 <- Sys.time()
running_rows <- 0L
for (i in seq_len(n_batches)) {
  chunks[[i]] <- fetch_batch(batches[[i]])
  running_rows <- running_rows + nrow(chunks[[i]])
  if (i %% 10 == 0 || i == n_batches) {
    elapsed <- as.numeric(Sys.time() - t_fetch0, units = "secs")
    cat(sprintf(
      "  batch %d/%d done, %d rows so far, %.1fs elapsed, ~%.1fs/batch\n",
      i, n_batches, running_rows, elapsed, elapsed / i
    ))
  }
}
fetch_elapsed <- as.numeric(Sys.time() - t_fetch0, units = "secs")

edges <- dplyr::bind_rows(chunks)
cat(sprintf("Fetched %d raw edges in %.1fs.\n", nrow(edges), fetch_elapsed))
rm(chunks)

if (nrow(edges) == 0) {
  fail("No edges retrieved - something is wrong with the query or connection.")
}

missing_source <- setdiff(unique(edges$source), all_node_ids)
missing_target <- setdiff(unique(edges$target), all_node_ids)
if (length(missing_source) > 0 || length(missing_target) > 0) {
  fail(
    "Edge endpoints missing from node census: %d missing sources, %d missing targets (e.g. %s)",
    length(missing_source), length(missing_target),
    paste(head(c(missing_source, missing_target), 5), collapse = ", ")
  )
}
cat("Validation: all edge endpoints present in node census.\n")

if (any(is.na(edges$weight)) || any(edges$weight <= 0)) {
  fail("Found non-positive or NA edge weight(s).")
}
cat("Validation: all weights positive.\n")

self_loops <- edges$source == edges$target
n_self_loops <- sum(self_loops)
cat(sprintf("Self-connections (source == target): %d\n", n_self_loops))

# Duplicate directed edges: expected to be zero (ConnectsTo is one relationship
# per ordered pair, batches partition source disjointly) - checked anyway, summed if found.
edge_key <- paste(edges$source, edges$target, sep = "->")
n_dup_rows <- sum(duplicated(edge_key))
if (n_dup_rows > 0) {
  cat(sprintf("Found %d duplicate directed-edge row(s); summing weights per (source,target).\n", n_dup_rows))
  edges <- dplyr::summarise(
    dplyr::group_by(edges, source, target),
    weight = sum(weight),
    .groups = "drop"
  )
  edges <- as.data.frame(edges)
} else {
  cat("Validation: no duplicate directed edges.\n")
}

n_edges <- nrow(edges)

w <- edges$weight
q <- stats::quantile(w, probs = c(0.75, 0.90, 0.95, 0.99), names = FALSE, type = 7)
weight_stats <- list(
  n = n_edges,
  min = min(w),
  median = stats::median(w),
  mean = mean(w),
  p75 = q[1],
  p90 = q[2],
  p95 = q[3],
  p99 = q[4],
  max = max(w)
)

cat(sprintf("\nTotal directed edges: %d\n", n_edges))
cat("Edge weight distribution:\n")
print(as.data.frame(weight_stats), row.names = FALSE)

raw_dir <- "data/raw"
if (!dir.exists(raw_dir)) dir.create(raw_dir, recursive = TRUE)
edges_path <- file.path(raw_dir, "io_edges.parquet")

edges_out <- edges[, c("source", "target", "weight")]
arrow::write_parquet(edges_out, edges_path, compression = "zstd")
file_size_bytes <- file.size(edges_path)
cat(sprintf(
  "\nSaved -> %s (%d rows, %.1f MB, zstd)\n",
  edges_path, n_edges, file_size_bytes / 1024^2
))

manifest <- list(
  dataset = "male-cns:v1.0",
  extraction_timestamp_utc = extraction_time,
  source_query = "MATCH (n:Neuron)-[c:ConnectsTo]->(m:Neuron) WHERE n.bodyId IN <batch> AND m.status = 'Traced' RETURN n.bodyId AS source, m.bodyId AS target, c.weight AS weight",
  node_filter = "both endpoints have status == 'Traced'",
  weight_threshold_applied = 1L,
  weight_threshold_note = "no connections discarded; threshold=1 is the ConnectsTo existence minimum, not a filter",
  batch_size = batch_size,
  n_batches = n_batches,
  fetch_elapsed_seconds = round(fetch_elapsed, 1),
  total_elapsed_seconds = round(as.numeric(Sys.time() - t_start, units = "secs"), 1),
  row_count = n_edges,
  file_path = edges_path,
  file_size_bytes = file_size_bytes,
  compression = "zstd",
  self_loop_count = n_self_loops,
  duplicate_directed_edges_merged = n_dup_rows,
  weight_stats = weight_stats
)
manifest_path <- file.path(raw_dir, "io_edges_manifest.json")
jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("Saved manifest -> %s\n", manifest_path))

cat("\nDone.\n")
