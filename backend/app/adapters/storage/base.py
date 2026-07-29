"""
Object storage interface.

Abstracts local file storage from the rest of the application.
"""

from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """
    Abstract storage interface for document files.

    Current implementation: LocalStorage, backed by the application's upload
    directory. Keeping the interface makes the API easy to test.
    """

    @abstractmethod
    async def upload(self, file_bytes: bytes, key: str) -> str:
        """
        Upload file bytes and return the storage path/URL.

        Args:
            file_bytes: Raw file content.
            key: Storage key (typically includes document_id and filename).

        Returns:
            The storage path or URL where the file was saved.
        """
        ...

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Download file bytes by storage key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a file by storage key. Returns True if deleted."""
        ...

    @abstractmethod
    async def get_url(self, key: str) -> str:
        """Get a URL/path to access the file."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a file exists at the given key."""
        ...
