"""Storage abstraction for source and generated objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    """Result of a storage write."""

    storage_uri: str
    checksum: str


class StorageService:
    """Abstract object storage interface."""

    def put_bytes(self, key: str, data: bytes, checksum: str) -> StoredObject:
        """Store bytes and return a stable URI."""

        return StoredObject(storage_uri=f"mock://storage/{key}", checksum=checksum)
