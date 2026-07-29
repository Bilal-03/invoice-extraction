from pathlib import Path

import pytest
from fastapi import HTTPException

from app.adapters.storage.local_storage import LocalStorage
from app.core.config import Settings
from app.core.security import create_access_token, verify_access_token
from app.core.uploads import sniff_mime_type, validate_upload


def test_jwt_round_trip_and_tamper_detection():
    settings = Settings(jwt_secret="test-secret", jwt_expiry_minutes=5)
    token, expires_in = create_access_token("reviewer", settings)
    assert expires_in == 300
    assert verify_access_token(token, settings) == "reviewer"
    with pytest.raises(ValueError):
        verify_access_token(token + "tampered", settings)


@pytest.mark.asyncio
async def test_upload_content_sniffing_rejects_extension_mismatch():
    settings = Settings(max_file_size_mb=1)
    assert sniff_mime_type(b"%PDF-1.7\n") == "application/pdf"
    mime_type, digest = await validate_upload("invoice.pdf", b"%PDF-1.7\n", settings)
    assert mime_type == "application/pdf"
    assert len(digest) == 64
    with pytest.raises(HTTPException) as exc:
        await validate_upload("invoice.png", b"%PDF-1.7\n", settings)
    assert exc.value.status_code == 415


def test_local_storage_blocks_path_traversal(tmp_path: Path):
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        storage._resolve_path("../outside.pdf")
