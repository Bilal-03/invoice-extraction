# Invoice Intelligence Platform

A full-stack accounts-payable automation platform for invoice ingestion, layout-aware OCR, structured extraction, validation, human review, audit, approvals, PO matching, payments, risk, aging, and analytics.

For laptop development the application uses FastAPI + Supabase Postgres + Supabase Storage. The
recommended local-full profile is PyMuPDF/OpenCV/Docling feeding PaddleOCR
PP-StructureV3, with Tesseract as the fallback and Ollama/Qwen3-VL or llama.cpp as
the local low-confidence verifier. On Intel macOS, the full backend runs in the
official Linux x86_64 Paddle Docker image; the host Python version is irrelevant.
The lightweight demo profile uses PyMuPDF/OpenCV/Tesseract and deterministic rules
only. Shared environments use Postgres, Supabase Storage, and a separate durable worker.

No paid AI or cloud-inference key is required; Supabase database and Storage credentials are required.

## Working features

- JPG, PNG, TIFF, and multi-page PDF ingestion; single and 25-file batch endpoints.
- Magic-byte MIME validation, size limits, sanitized filenames, exact-content duplicate detection, SHA-256 invoice fingerprints (supplier GSTIN + invoice number + invoice date + grand total), legacy business-key duplicate fallback, optional ClamAV hook, and path traversal protection.
- OpenCV resize, grayscale, best-effort orientation correction, quality-aware denoising, CLAHE contrast enhancement, adaptive thresholding, and deskew preprocessing. Original uploads remain untouched; processed pages and transform metadata are persisted per document/page.
- A universal nested `InvoiceDataStandard` (`invoice`, `seller`, `buyer`, `items`, `taxes`, `totals`, `payment`, and `einvoice`) is attached to every projected extraction while provenance-rich fields remain available for human review.
- Embedded-text-first extraction for digital PDFs, with PyMuPDF coordinates, optional Docling structure/tables, and word-level PaddleOCR/Tesseract evidence for scanned documents.
- A pluggable spatial layout extractor covering invoice number/dates, PO/order reference, terms, vendor/GSTIN/address, buyer billing/shipping details, taxes, currency, full totals, and multi-line table items.
- Confidence-gated local Ollama/Qwen3-VL or llama.cpp verification, with deterministic rules continuing when local AI is unavailable.
- Ask Invoice AI on invoice detail pages: Ollama/Qwen3-VL receives only the bounded invoice JSON and OCR text, returns grounded evidence paths, and falls back to deterministic answers when the local model is unavailable.
- Optional PaddleOCR 3.x PP-StructureV3 OCR/layout/table processing, with Tesseract as the resilient backup.
- OpenCV QR detection scans all rendered pages, parses common e-invoice JSON/base64/key-value payloads, and compares QR invoice number/date/GSTIN/tax/total evidence with OCR without overwriting extracted values.
- Supabase-persisted AP projections for users, invoices, line items, taxes, vendors, purchase orders, goods receipts, validations, invoice flags, AI extractions, human corrections, payments, and append-only audit logs.
- Approval guards, deterministic Invoice Risk & Anomaly Detection, two-way PO matching, three-way PO/receipt/invoice matching, partial payments, AP aging, and CSV/XLSX/JSON import/export. Risk scores are capped at 100 and are the sum of explainable persisted contributions such as duplicate (+40), bank-detail change (+25), unknown vendor (+15), PO mismatch (+15), and amount anomaly (+10); no model invents the score.
- Modular validation families under `backend/app/validation/`: invoice identity, amounts, dates, GSTIN/PAN, GST mode, and duplicate fingerprints. Amount checks reconcile subtotal - discount + tax + shipping against the invoice total with an explainable calculated/invoice/difference breakdown. GST checks are explicitly automated consistency checks, not legal compliance verification.
- Vendor master resolution searches by normalized GSTIN first and normalized vendor name second, creates new vendors automatically, and exposes invoice count, total invoiced spend, paid-through-outstanding balance, contact, bank, IFSC, and payment-term fields.
- Durable job states, audit history, and human corrections persisted in Supabase Postgres and Supabase Storage.
- API-key or HS256 bearer authentication, CORS, rate limiting, readiness/liveness probes, structured logs, and Prometheus metrics.
- OpenTelemetry tracing for API, database, queue, worker, and extraction stages with optional OTLP/HTTP export.
- React/Vite AP console with batch upload, live status polling, filters, authenticated multi-page image/PDF preview, confidence boxes, editable fields, validation flags, audit timeline, vendor spend, payments, and processing trends.
- Invoice search covers invoice number, vendor, GSTIN, PO, amount, invoice/due date, and status, with pagination and the existing structured filters.
- Evaluation CLI producing JSON and Markdown metrics and CI gates.

## Architecture

```text
React/Vite → FastAPI → Supabase Postgres + Supabase Storage
                    ↓
           durable document-job queue
                    ↓
 PyMuPDF → OpenCV → Docling (optional structure)
                    ↓
 PaddleOCR PP-StructureV3 → Tesseract fallback
                    ↓
 rule extractor → Pydantic → validation → confidence/risk → review → AP workflow
                                      ↓
                      Ollama/Qwen3-VL or llama.cpp when uncertain
```

See [docs/architecture.md](docs/architecture.md) for the adapter boundaries and security model.

## Run locally with Supabase

Prerequisites: a Supabase project, Python 3.10+, Node.js 20+, and Tesseract on `PATH`.
For the full Intel-Mac path, install Docker Desktop and use the compose workflow below;
the Paddle container supplies its own Linux/Python runtime.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # fill DATABASE_URL and Supabase secrets
alembic upgrade head
uvicorn app.main:app --reload
```

In a second shell, start the durable worker:

```bash
cd backend
source .venv/bin/activate
python -m app.worker
```

Then start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). OpenAPI documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

For a ready-to-view fictional workspace, run the idempotent seed command:

```bash
cd backend
python -m app.seed
```

Use `python -m app.seed --reset` to remove only the seeded records and recreate them. Run `python -m app.backfill` after the AP migration to project existing completed documents. Profiles are `local-full` (PP-StructureV3 when installed, Tesseract fallback, Docling/PyMuPDF parsing, Ollama optional) and `demo-lite` (Tesseract, PyMuPDF, and deterministic rules only).

## Full local stack in Docker (Intel macOS)

The Docker image is based on `paddlepaddle/paddle:3.3.0`, which supplies Linux
x86_64, Python 3.10, and PaddlePaddle. The image installs PaddleOCR's `doc-parser`
dependency group for PP-StructureV3, plus CPU-only PyTorch for Docling. This follows the official
[PaddlePaddle Docker instructions](https://www.paddlepaddle.org.cn/documentation/docs/en/install/docker/linux-docker_en.html)
and [PaddleOCR installation groups](https://www.paddleocr.ai/main/en/version3.x/installation.html).

From the repository root, copy and fill the Supabase settings first:

```bash
cp backend/.env.example backend/.env
# edit backend/.env with the Supabase database URL, project URL, and service-role key
```

Then run:

```bash
docker compose build backend-image
docker compose --profile seed run --rm seed
docker compose up api worker frontend
```

Open [http://localhost:5173](http://localhost:5173). The API is at
[http://localhost:8000](http://localhost:8000). The migration container applies Alembic
to Supabase before the API and worker start. Verify the container engines with:

```bash
docker compose run --rm backend-image python -c "import paddle; print(paddle.__version__)"
docker compose run --rm backend-image python -c "from paddleocr import PPStructureV3; print('PP-StructureV3 ready')"
```

Docker Desktop exposes the host Ollama server as `host.docker.internal`. After
installing Ollama and pulling the model, enable it with:

```bash
ollama pull qwen3-vl:2b
VLM_ENABLED=true docker compose up api worker frontend
```

The 2B model is the recommended starting point for CPU-only Intel Macs. To try the
larger local model, pull `qwen3-vl:4b` and set `OLLAMA_MODEL=qwen3-vl:4b`. The worker
does not call Ollama for every invoice: Paddle/Tesseract, layout rules, and validation
run first; Ollama is requested only for missing/low-confidence fields or failed checks.
Its JSON response is validated by the local Pydantic contract before it can be merged.

To use a local llama.cpp server instead, set `VLM_PROVIDER=llama.cpp` and configure
`LLAMA_CPP_BASE_URL`/`LLAMA_CPP_MODEL` before starting Compose. Both providers are
optional; deterministic extraction continues when neither is available.

## Supabase database and storage

Configure the Supabase database URL and private Storage credentials in `backend/.env`,
install dependencies, apply migrations, then run the API and a separate durable worker:

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
# another terminal
python -m app.worker
```

Set `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` using
the server-only values from the Supabase dashboard. Never add the service-role key to a
frontend environment file. Jobs remain queued safely in Supabase Postgres whenever the
worker is not running. See `docs/production-readiness.md` for operations and retention guidance.

Use `backend/.env` for optional authentication or local Ollama settings. Never commit real keys.

## Deploy to Render and Vercel

The repository includes [`render.yaml`](render.yaml), which creates a free Render
Web Service using `backend/Dockerfile.demo`. It runs the Supabase migrations at
startup, serves the API on Render's `PORT`, and enables the embedded worker because
Render's free tier does not include a free Background Worker. This profile uses
Tesseract plus deterministic rules; PaddleOCR/PP-StructureV3 and Ollama remain in
the local-full Docker profile.

1. In Render, choose **New → Blueprint**, connect the GitHub repository, and apply
   `render.yaml`. Fill the four `sync: false` values when Render prompts for them:

   - `DATABASE_URL`: Supabase pooler URL using the `postgresql+asyncpg://` scheme.
   - `SUPABASE_URL`: `https://<project-ref>.supabase.co`.
   - `SUPABASE_SERVICE_ROLE_KEY`: Supabase server-only service-role key.
   - `CORS_ORIGINS`: JSON list containing the final Vercel origin, for example
     `["https://your-app.vercel.app"]`.

   Never put the service-role key or database URL in Vercel. Render's filesystem is
   ephemeral, so uploads use the private Supabase Storage bucket.
   Before the first upload, create a **private** Supabase Storage bucket named
   `documents` (or change `SUPABASE_STORAGE_BUCKET` in the Blueprint and use that
   name instead).
2. After the API deploys, copy its URL, such as
   `https://invoice-intelligence-api.onrender.com`.
3. In Vercel, import the same repository, set **Root Directory** to `frontend`,
   and add this client-side variable:

   ```text
   VITE_API_URL=https://invoice-intelligence-api.onrender.com
   ```

   Do not append `/api/v1`; the typed client adds that path. The included
   `frontend/vercel.json` keeps React Router deep links working.
4. Replace `CORS_ORIGINS` in Render with the exact Vercel production URL (and any
   custom frontend domain), then redeploy the API. Preview URLs need to be added
   separately if you want to use them.

For a public portfolio demo, leave `API_KEY`, `AUTH_USERNAME`, `AUTH_PASSWORD`, and
`JWT_SECRET` unset. For a protected deployment, set `API_KEY` or all three JWT
settings in Render and use the frontend's stored API credentials; never expose
backend secrets as `VITE_*` variables.

The free Render Web Service sleeps after inactivity. Supabase retains queued jobs,
but processing resumes only when the service wakes. For a paid deployment, run a
separate Render Background Worker with `python -m app.worker` and set
`EMBEDDED_WORKER_ENABLED=false` on the Web Service.

## Optional local extraction adapters

The native full extra is intended for a supported host or Linux environment. On an
Intel Mac, use the Docker workflow above so PaddlePaddle runs in Linux x86_64. The
full image is `backend/Dockerfile`; the lightweight Tesseract-only image is
`backend/Dockerfile.demo`.

```bash
cd backend
pip install -e ".[local-full]"
alembic upgrade head
PIPELINE_PROFILE=local-full OCR_ENGINE=pp-structure-v3 DOCUMENT_PARSER=auto uvicorn app.main:app
```

The local profile uses Ollama only when confidence or validation signals require it. If Ollama is not installed or reachable, extraction continues with Paddle/Tesseract and deterministic rules. Ollama is free and local:

```bash
ollama serve
ollama pull qwen3-vl:2b
VLM_PROVIDER=ollama VLM_ENABLED=true uvicorn app.main:app
```

For the provider-independent llama.cpp path:

```bash
VLM_PROVIDER=llama.cpp \
LLAMA_CPP_BASE_URL=http://127.0.0.1:8080 \
LLAMA_CPP_MODEL=local-model \
VLM_ENABLED=true uvicorn app.main:app
```

If the optional PaddleOCR or Docling wheels are unavailable on a host, the API
reports the active provider and continues through the free deterministic fallback path.

## Authentication

Leave credentials empty for the public portfolio demo. Set `API_KEY` for programmatic
clients, or set `AUTH_USERNAME`, `AUTH_PASSWORD`, and `JWT_SECRET` together for
bearer login. The Vite client reads optional browser-local values named
`invoice_api_key` and `invoice_access_token`; there is intentionally no `VITE_API_KEY`
setting because every `VITE_*` value is exposed in the browser bundle.

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
GET    /api/v1/dashboard/summary
GET    /api/v1/analytics/ap
GET    /api/v1/provider/status
GET    /api/v1/invoices
GET    /api/v1/invoices/{id}
POST   /api/v1/invoices/{id}/qa
POST   /api/v1/invoices/{id}/actions
POST   /api/v1/invoices/{id}/payments
GET    /api/v1/payments
GET    /api/v1/vendors
GET    /api/v1/purchase-orders
POST   /api/v1/purchase-orders/import
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

Generate a local labeled starter set with distortions and export human corrections with:

```bash
python -m eval.generate_synthetic --output-dir /private/tmp/invoice-synthetic --count 20 --distorted
python -m eval.export_corrections --output /private/tmp/ap-corrections.jsonl
```

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
frontend/src/       React/Vite AP console
docker-compose.yml  Intel-Mac Docker stack (Paddle backend, worker, Supabase, frontend)
backend/Dockerfile.demo  lightweight Tesseract-only container
docs/               architecture and API examples
.github/workflows/  CI pipeline
```

## License

MIT — see [LICENSE](LICENSE).
