"""Upload hardening: content sniffing, hashing, and an optional malware hook."""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException

from app.core.config import Settings

MAGIC_TYPES = {
    b"%PDF": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
}

MIME_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/tiff": {".tif", ".tiff"},
}


def sniff_mime_type(data: bytes) -> str | None:
    for signature, mime_type in MAGIC_TYPES.items():
        if data.startswith(signature):
            return mime_type
    return None


async def validate_upload(filename: str, data: bytes, settings: Settings) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension not in settings.allowed_extensions:
        raise HTTPException(
            status_code=415, detail=f"Unsupported file extension: {extension or 'none'}"
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_file_size_mb} MB upload limit",
        )
    mime_type = sniff_mime_type(data)
    if not mime_type or extension not in MIME_EXTENSIONS[mime_type]:
        raise HTTPException(
            status_code=415,
            detail="File content does not match a supported PDF or image type",
        )
    if settings.clamav_enabled:
        await _scan_with_clamav(data, extension, settings.clamav_command)
    return mime_type, hashlib.sha256(data).hexdigest()


async def _scan_with_clamav(data: bytes, extension: str, command: str) -> None:
    file_descriptor, temp_path = tempfile.mkstemp(suffix=extension)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(data)
        process = await asyncio.create_subprocess_exec(
            command,
            "--no-summary",
            temp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode == 1:
            raise HTTPException(status_code=422, detail="Malware scan rejected the uploaded file")
        if process.returncode != 0:
            raise HTTPException(status_code=503, detail="Malware scanner is unavailable")
    finally:
        Path(temp_path).unlink(missing_ok=True)
