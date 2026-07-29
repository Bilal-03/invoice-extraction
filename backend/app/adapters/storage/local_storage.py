"""
Local filesystem storage implementation.

Stores uploaded documents on the local filesystem with no external services.
"""

from pathlib import Path

import aiofiles

from app.adapters.storage.base import ObjectStorage
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LocalStorage(ObjectStorage):
    """Local filesystem-backed object storage."""

    def __init__(self, base_dir: str | None = None):
        settings = get_settings()
        self.base_dir = Path(base_dir or settings.upload_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("local_storage_initialized", base_dir=str(self.base_dir))

    def _resolve_path(self, key: str) -> Path:
        """Resolve a storage key to a filesystem path."""
        path = self.base_dir / key
        # Security: prevent path traversal
        path.resolve().relative_to(self.base_dir.resolve())
        return path

    async def upload(self, file_bytes: bytes, key: str) -> str:
        """Write file bytes to the local filesystem."""
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(path, "wb") as f:
            await f.write(file_bytes)

        logger.info(
            "file_uploaded",
            key=key,
            size_bytes=len(file_bytes),
            path=str(path),
        )
        return str(path)

    async def download(self, key: str) -> bytes:
        """Read file bytes from the local filesystem."""
        path = self._resolve_path(key)
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> bool:
        """Delete a file from the local filesystem."""
        path = self._resolve_path(key)
        if path.exists():
            path.unlink()
            logger.info("file_deleted", key=key)
            return True
        return False

    async def get_url(self, key: str) -> str:
        """Return the filesystem path as a URL-like string."""
        return f"/api/v1/documents/file/{key}"

    async def exists(self, key: str) -> bool:
        """Check if a file exists on the local filesystem."""
        return self._resolve_path(key).exists()
