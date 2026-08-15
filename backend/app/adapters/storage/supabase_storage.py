"""Private Supabase Storage adapter using the Storage REST API."""

import asyncio

import httpx

from app.adapters.storage.base import ObjectStorage
from app.core.logging import get_logger

logger = get_logger(__name__)


class SupabaseStorage(ObjectStorage):
    """Store documents in a private Supabase bucket using server credentials."""

    def __init__(self, url: str, service_role_key: str, bucket: str = "documents"):
        self.url = url.rstrip("/")
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key}

    def _object_url(self, key: str) -> str:
        return f"{self.url}/storage/v1/object/{self.bucket}/{key}"

    async def upload(self, file_bytes: bytes, key: str) -> str:
        def request() -> None:
            response = httpx.post(
                self._object_url(key),
                headers={
                    **self.headers,
                    "Content-Type": "application/octet-stream",
                    # Processed page keys are deterministic so reprocessing a
                    # document replaces the previous evidence instead of
                    # leaving orphaned objects behind.
                    "x-upsert": "true",
                },
                content=file_bytes,
                timeout=60,
            )
            response.raise_for_status()

        await asyncio.to_thread(request)
        logger.info("supabase_file_uploaded", key=key, size_bytes=len(file_bytes))
        return key

    async def download(self, key: str) -> bytes:
        def request() -> bytes:
            response = httpx.get(self._object_url(key), headers=self.headers, timeout=60)
            response.raise_for_status()
            return response.content

        return await asyncio.to_thread(request)

    async def delete(self, key: str) -> bool:
        def request() -> bool:
            response = httpx.request(
                "DELETE",
                f"{self.url}/storage/v1/object/{self.bucket}",
                headers=self.headers,
                json={"prefixes": [key]},
                timeout=30,
            )
            response.raise_for_status()
            return True

        return await asyncio.to_thread(request)

    async def get_url(self, key: str) -> str:
        def request() -> str:
            response = httpx.post(
                f"{self.url}/storage/v1/object/sign/{self.bucket}/{key}",
                headers=self.headers,
                json={"expiresIn": 300},
                timeout=30,
            )
            response.raise_for_status()
            signed_path = response.json()["signedURL"]
            return (
                signed_path
                if signed_path.startswith("http")
                else f"{self.url}/storage/v1{signed_path}"
            )

        return await asyncio.to_thread(request)

    async def exists(self, key: str) -> bool:
        try:
            await self.download(key)
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise
