# 0003 – Vector search uses local FAISS files, not SQL Server

**Status:** accepted (2026-11-08)

## Context
Text search and "find similar" (spec F13) need nearest-neighbour search over image embeddings.
The dev database is SQL Server 2022, which has no native vector type (it arrives in SQL Server 2025).

## Decision
Embeddings are stored in FAISS index files per day under `data/retail_embeddings/`; metadata
(camera, track, times, crop path, colour, plate) stays in a SQL table `track_index`. Old days are
dropped by the retention job.

## Consequences
- No database upgrade needed; search works offline on the site server.
- Index files must be backed up / deleted alongside the SQL metadata.
