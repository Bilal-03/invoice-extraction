# Architecture

The API accepts validated PDF/image uploads, stores the raw file locally, persists a pending document record in SQLite, and dispatches an in-process extraction job through FastAPI background tasks.

```mermaid
flowchart LR
  UI[Next.js review dashboard] --> API[FastAPI v1 API]
  API --> DB[(SQLite)]
  API --> Store[Local uploads]
  API --> Job[FastAPI background task]
  Job --> Pre[OpenCV preprocessing]
  Pre --> OCR[PaddleOCR / Tesseract fallback]
  OCR --> Layout[Spatial layout extractor]
  Layout --> Validate[Domain validation]
  Validate -->|low confidence| VLM[Gemini fallback]
  Validate --> DB
  VLM --> DB
```

The domain schema is the serialization boundary shared by the API, JSON database column, audit workflow, benchmark harness, and TypeScript client types. Optional adapters fail closed or fall back to deterministic local implementations.

## Security boundaries

- Upload content is magic-byte sniffed, size-limited, filename-sanitized, path-contained, and optionally scanned by ClamAV.
- API-key and HS256 bearer authentication are enabled only when credentials are configured, keeping local setup frictionless.
- Protected previews are downloaded through the authenticated API client as blob URLs.
- Secrets are environment variables; no provider key is stored in source.
