# API examples

```bash
curl -F file=@invoice.pdf http://localhost:8000/api/v1/documents
curl http://localhost:8000/api/v1/documents/DOCUMENT_ID
curl http://localhost:8000/api/v1/documents/DOCUMENT_ID/audit
```

Batch upload:

```bash
curl -F files=@invoice-1.pdf -F files=@invoice-2.png \
  http://localhost:8000/api/v1/documents/batch
```

Correction and audit:

```bash
curl -X PATCH -H 'Content-Type: application/json' \
  -d '{"field_path":"grand_total","new_value":"1250.00","corrected_by":"reviewer"}' \
  http://localhost:8000/api/v1/documents/DOCUMENT_ID/fields
```

When `API_KEY` is configured, add `-H 'X-API-Key: ...'`. For dashboard login, request a bearer token from `POST /api/v1/auth/token` with `{"username":"...","password":"..."}`.
