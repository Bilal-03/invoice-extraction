# Production readiness review

## Changes delivered

- Uploads enqueue durable Supabase Postgres jobs; extraction runs in `python -m app.worker` rather than FastAPI background tasks. Supabase Storage is the only runtime file store.
- The local-full profile uses PyMuPDF/OpenCV, optional Docling structure extraction, and PaddleOCR PP-StructureV3 with Tesseract fallback. It only invokes local Ollama/Qwen3-VL or llama.cpp when confidence or validation signals require it.
- OpenTelemetry spans cover FastAPI requests, SQLAlchemy queries, queue claims, worker jobs, storage download, preprocessing, OCR, layout extraction, validation, Ollama verification, and persistence. Configure `TRACING_OTLP_ENDPOINT` to export them to an OTLP/HTTP collector.
- A single Render Web Service can run the embedded worker for free-tier deployments; this is a budget mode because worker availability follows web-service sleep behavior.

- Digital PDFs use PyMuPDF's embedded text layer and native word coordinates; Docling can add normalized reading order and table structure when installed. They avoid unnecessary raster OCR while retaining review overlays.
- Scanned documents keep the existing raster OCR path, now rendered at a lower 160 DPI default and without Tesseract's duplicate `image_to_string` invocation.
- PDF previews render only the selected page rather than every page in the file.
- Worker extraction is bounded by `PIPELINE_MAX_CONCURRENCY` (default `2`) so a batch cannot exhaust CPU and degrade API responsiveness.
- The review and analytics interfaces load only when selected, reducing initial JavaScript shipped to the workspace.

## Observed production risks

The durable job queue supports horizontally scaled workers, but the following work remains before calling the deployment production-ready:

- Supabase migrations must run with `alembic upgrade head` before the API or worker is deployed. Startup verifies the migrated database but never creates an untracked schema.
- Worker concurrency and failure recovery have not yet been load-tested across multiple replicas.
- The current dashboard polls; this is fine for low volume but inefficient at scale.

## Recommended rollout

1. Introduce server-sent events or WebSockets for status updates. Retain polling as a fallback.
2. Instrument p50/p95 latency per stage (render, preprocess, OCR, extraction, VLM), queue depth, retry count, and extraction quality. Set SLOs before increasing concurrency.
3. Add a dead-letter workflow, bounded retries for transient storage/VLM failures, and an explicit manual reprocess endpoint.
4. Add tenant ownership and authorization to documents, audit entries, storage keys, analytics queries, and rate-limit keys before offering multi-tenant access.

## Capacity guidance

Start worker concurrency at `min(2, CPU cores - 1)` for Tesseract workloads; benchmark representative scans before raising it. Text-native PDFs should use negligible worker time, while photographed or multi-page scans are the capacity driver. Scale worker replicas from queue depth and measured p95 processing time, not upload request volume.
