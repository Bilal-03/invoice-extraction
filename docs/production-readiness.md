# Production readiness review

## Changes delivered

- Digital PDFs now use their embedded text layer and native word coordinates. They bypass PDF rasterisation, OpenCV preprocessing, and Tesseract while retaining review overlays.
- Scanned documents keep the existing raster OCR path, now rendered at a lower 160 DPI default and without Tesseract's duplicate `image_to_string` invocation.
- PDF previews render only the selected page rather than every page in the file.
- In-process extraction is bounded by `PIPELINE_MAX_CONCURRENCY` (default `2`) so a batch cannot exhaust CPU and degrade API responsiveness.
- The review and analytics interfaces load only when selected, reducing initial JavaScript shipped to the workspace.

## Observed production risks

The current application is a strong single-node deployment, but it is not horizontally scalable yet. Its state and job execution are local to an API instance:

- SQLite permits limited concurrent write throughput and a local uploads directory is not shared across replicas.
- FastAPI background tasks disappear on deploy/restart and do not provide durable retries, delayed jobs, or back-pressure across instances.
- Long OCR and VLM work takes place in the API process, competing with uploads and reads.
- The current dashboard polls; this is fine for low volume but inefficient at scale.

## Recommended rollout

1. Replace SQLite with PostgreSQL and local files with S3/GCS-compatible object storage. Add a migration tool such as Alembic and a retention policy for source files and previews.
2. Move `run_extraction_pipeline` behind a durable queue (Celery/RQ/Arq, SQS, or a managed workflow). Run OCR workers separately from API replicas; make jobs idempotent with the existing content hash.
3. Introduce a job event store and server-sent events or WebSockets for status updates. Retain polling as a fallback.
4. Instrument p50/p95 latency per stage (render, preprocess, OCR, extraction, VLM), queue depth, retry count, and extraction quality. Set SLOs before increasing concurrency.
5. Add a dead-letter workflow, bounded retries for transient storage/VLM failures, and an explicit manual reprocess endpoint.
6. Add tenant ownership and authorization to documents, audit entries, storage keys, analytics queries, and rate-limit keys before offering multi-tenant access.

## Capacity guidance

Start worker concurrency at `min(2, CPU cores - 1)` for Tesseract workloads; benchmark representative scans before raising it. Text-native PDFs should use negligible worker time, while photographed or multi-page scans are the capacity driver. Scale worker replicas from queue depth and measured p95 processing time, not upload request volume.
