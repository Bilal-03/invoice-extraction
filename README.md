# Invoice Intelligence Platform

A full-stack intelligent document processing system for invoice ingestion, layout-aware OCR, structured extraction, validation, human review, audit, and analytics.

The application runs entirely on a laptop: FastAPI + SQLite + local file storage +
in-process background tasks + Tesseract. It needs no Docker or external services.

No cloud key is required for the deterministic pipeline.

## Working features

- JPG, PNG, TIFF, and multi-page PDF ingestion; single and 25-file batch endpoints.
- Magic-byte MIME validation, size limits, sanitized filenames, exact-content duplicate detection, business-key duplicate warnings, optional ClamAV hook, and path traversal protection.
- OpenCV grayscale, quality-aware denoising, adaptive thresholding, and deskew preprocessing.
- Embedded-text-first extraction for digital PDFs, with word-level Tesseract/PaddleOCR coordinates and spatial column reconstruction for scanned documents.
- A pluggable spatial layout extractor covering invoice number/dates, PO/order reference, terms, vendor/GSTIN/address, buyer billing/shipping details, taxes, currency, full totals, and multi-line table items.
- Confidence-gated Gemini structured-output fallback when explicitly enabled.
- Arithmetic, date, GSTIN, required-field, and duplicate validation flags.
- SQLite persistence, local file storage, progressive job states, audit history, and human corrections.
- API-key or HS256 bearer authentication, CORS, rate limiting, readiness/liveness probes, structured logs, and Prometheus metrics.
- Next.js dashboard with batch upload, live status polling, filters, authenticated image/PDF preview, confidence boxes, editable fields, validation flags, audit timeline, vendor spend, and processing trends.
- Evaluation CLI producing JSON and Markdown metrics and CI gates.

## Architecture

```text
Next.js → FastAPI → SQLite metadata DB + local uploads
                    ↓
       in-process background extraction
                    ↓
 preprocess → OCR fallback chain → spatial extraction → validate → optional VLM → persist
```

See [docs/architecture.md](docs/architecture.md) for the adapter boundaries and security model.

## Run locally

Prerequisites: Python 3.11+, Node.js 20+, and Tesseract on `PATH`.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

In a second shell:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). OpenAPI documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

The SQLite database and local upload directory are created automatically at startup.
Data is stored in `backend/data/invoices.db` and `backend/data/uploads`.

Use `backend/.env` for optional authentication or external-VLM settings. Never commit real keys.

## Deploy to Render and Vercel

The repository includes a production Docker configuration for the FastAPI API on
Render and a Vercel configuration for the Next.js dashboard.

1. In Render, create a Blueprint from this repository. It uses `render.yaml` to
   create the API service and a persistent disk for SQLite data and uploaded
   invoices. Once the service is live, copy its URL (for example,
   `https://invoice-extraction-api.onrender.com`).
2. In Vercel, import the same repository and set **Root Directory** to
   `frontend`. Add `NEXT_PUBLIC_API_URL` with the Render API URL, then deploy.
3. Back in Render, set `CORS_ORIGINS` to a JSON list containing the Vercel URL,
   for example `[“https://your-app.vercel.app”]`, and redeploy the API.

For a protected API, also set `API_KEY`, or set `AUTH_USERNAME`,
`AUTH_PASSWORD`, and a strong `JWT_SECRET` in Render. Do not put backend
secrets in Vercel.

## Optional extraction adapters

PaddleOCR is an optional high-accuracy primary engine:

```bash
cd backend
pip install -e ".[paddleocr]"
OCR_ENGINE=paddleocr uvicorn app.main:app
```

Gemini is only called when `VLM_ENABLED=true`, a key is configured, and deterministic confidence is below `VLM_CONFIDENCE_THRESHOLD` or required fields are absent:

```bash
pip install -e ".[vlm]"
VLM_ENABLED=true GEMINI_API_KEY=... uvicorn app.main:app
```

## Authentication

Leave credentials empty for open local development. Set `API_KEY` for programmatic clients, or set `AUTH_USERNAME`, `AUTH_PASSWORD`, and `JWT_SECRET` together for dashboard bearer login. The UI's “API access” dialog stores the selected credential in browser local storage.

## API

Core endpoints:

```text
POST   /api/v1/documents
POST   /api/v1/documents/batch
GET    /api/v1/documents
GET    /api/v1/documents/{id}
GET    /api/v1/documents/{id}/events
PATCH  /api/v1/documents/{id}/fields
GET    /api/v1/documents/{id}/audit
GET    /api/v1/analytics/summary
GET    /api/v1/analytics/vendors
GET    /api/v1/analytics/trends
POST   /api/v1/auth/token
GET    /health
GET    /ready
GET    /metrics
```

See [docs/api_examples.md](docs/api_examples.md) for curl examples.

## Evaluation

Create a manifest whose `file` paths are relative to the manifest and whose `expected` objects use the extraction schema, then run:

```bash
cd backend
python -m eval.run_benchmark eval/datasets/manifest.json --output-dir eval/results
```

The harness reports field precision/recall/F1, strict document exact match, line-item row F1 and cell accuracy, p50/p95 latency, extraction-source split, and VLM fallback rate. It intentionally ships without invented benchmark numbers; place SROIE/CORD-derived data under the gitignored dataset directory and report measured results.

## Quality gates

```bash
cd backend
ruff check app tests eval
ruff format --check app tests eval
pytest --cov=app

cd ../frontend
npm run lint
npm run build
```

CI runs the same backend and frontend checks.

## Project layout

```text
backend/app/        FastAPI, domain, services, adapters, tasks
backend/eval/       benchmark runner
backend/tests/      unit and API tests
frontend/src/       Next.js dashboard
docs/               architecture and API examples
.github/workflows/  CI pipeline
```

## License

MIT — see [LICENSE](LICENSE).
