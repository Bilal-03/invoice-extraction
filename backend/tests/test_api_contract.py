from app.main import app


def test_openapi_contains_public_contract():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/documents",
        "/api/v1/documents/batch",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/preview",
        "/api/v1/documents/{document_id}/fields",
        "/api/v1/documents/{document_id}/audit",
        "/api/v1/documents/{document_id}/events",
        "/api/v1/analytics/summary",
        "/api/v1/analytics/vendors",
        "/api/v1/analytics/trends",
        "/api/v1/auth/token",
        "/health",
        "/ready",
    }
    assert expected <= set(paths)
