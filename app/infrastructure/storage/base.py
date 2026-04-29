from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, Union, BinaryIO, List
from abc import ABC, abstractmethod
from enum import Enum
import asyncio


class StorageBackendType(str, Enum):
    """Supported storage backend identifiers (used in config STORAGE__BACKEND)."""
    LOCAL = "local"
    S3    = "s3"    # AWS S3 and any S3-compatible (MinIO, Wasabi, Backblaze B2 …)




@dataclass
class StorageFileInfo:
    """
    Metadata about a stored file.

    identifier  – backend-specific key (relative path, S3 object key, etc.)
    url         – URL for accessing the file (may be presigned or public)
    """
    identifier: str         # e.g. "images/avatar_123.png"
    filename: str           # original filename
    size: int               # bytes
    content_type: str       # MIME type, e.g. "image/jpeg"
    created_at: datetime
    modified_at: datetime
    checksum: str           # MD5 hex digest
    url: str = ""           # access URL (public or presigned)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict (JSON-safe values)."""
        return {
            "identifier":   self.identifier,
            "filename":     self.filename,
            "size":         self.size,
            "content_type": self.content_type,
            "created_at":   self.created_at.isoformat(),
            "modified_at":  self.modified_at.isoformat(),
            "checksum":     self.checksum,
            "url":          self.url,
            "metadata":     self.metadata,
        }


@dataclass
class StorageUploadResult:
    """
    Result returned after a successful upload operation.

    Extends StorageFileInfo with upload-specific fields like the backend
    that performed the operation and a pre-computed access URL.
    """
    file_info: StorageFileInfo
    backend:   str              # backend type name, e.g. "s3"
    public_url: str = ""        # permanent public URL (if object is public)
    presigned_url: str = ""     # time-limited presigned URL (if applicable)

    @property
    def url(self) -> str:
        """Best available URL: public_url > presigned_url > file_info.url."""
        return self.public_url or self.presigned_url or self.file_info.url

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.file_info.to_dict(),
            "backend":      self.backend,
            "public_url":   self.public_url,
            "presigned_url": self.presigned_url,
            "url":          self.url,
        }
    

class StorageBackend(ABC):
    """
    Abstract base class for all storage adapters.

    Every adapter MUST implement the six abstract methods below.
    Concrete implementations should also set the `backend_type` class variable.

    Optional: override the `async_*` methods for true non-blocking I/O.
    If not overridden, the async methods fall back to running the sync
    version in a thread-pool executor so they remain awaitable.

    Custom adapters can be registered at runtime via StorageManager.register().
    """

    # Subclasses should override this with the matching StorageBackendType value
    backend_type: str = "unknown"

    # ── Abstract interface (MUST be implemented) ──────────────────────────────

    @abstractmethod
    def save_file(
        self,
        file_data: Union[bytes, BinaryIO],
        filename: str,
        subfolder: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> StorageFileInfo:
        """
        Persist file_data to storage and return its metadata.

        Args:
            file_data:  File content as bytes or a file-like object.
            filename:   Original filename (used for extension / MIME detection).
            subfolder:  Optional logical sub-path inside the storage root.
            metadata:   Arbitrary key-value pairs to attach to the object.
            **kwargs:   Backend-specific options (e.g. ACL, StorageClass).

        Returns:
            StorageFileInfo describing the stored file.
        """

    @abstractmethod
    def get_file(self, identifier: str) -> bytes:
        """
        Download and return the raw bytes of a stored file.

        Args:
            identifier: Backend-specific key (path / object key / ID).

        Returns:
            File content as bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
        """

    @abstractmethod
    def get_file_info(self, identifier: str) -> StorageFileInfo:
        """
        Return metadata for a stored file without downloading it.

        Args:
            identifier: Backend-specific key.

        Returns:
            StorageFileInfo.

        Raises:
            FileNotFoundError: If the file does not exist.
        """

    @abstractmethod
    def delete_file(self, identifier: str) -> bool:
        """
        Remove a file from storage.

        Args:
            identifier: Backend-specific key.

        Returns:
            True if the file was deleted, False if it was not found.
        """

    @abstractmethod
    def file_exists(self, identifier: str) -> bool:
        """
        Check whether a file exists in storage.

        Args:
            identifier: Backend-specific key.

        Returns:
            True if the file exists.
        """

    @abstractmethod
    def list_files(
        self,
        subfolder: Optional[str] = None,
        pattern: str = "*",
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[StorageFileInfo]:
        """
        Enumerate files in storage (optionally within a subfolder).

        Args:
            subfolder:  Limit listing to this sub-path (None = root).
            pattern:    Glob-style filename filter (e.g. "*.jpg").
            limit:      Maximum number of results to return.
            **kwargs:   Backend-specific options (e.g. continuation token).

        Returns:
            List of StorageFileInfo objects.
        """

    @abstractmethod
    def get_file_url(
        self,
        identifier: str,
        expires_in: Optional[int] = None,
        **kwargs,
    ) -> str:
        """
        Return a URL that can be used to access the file.

        For public endpoints this is a permanent URL.
        For private storage this is a presigned / time-limited URL.

        Args:
            identifier:  Backend-specific key.
            expires_in:  Seconds until the URL expires (None = backend default).
            **kwargs:    Backend-specific options.

        Returns:
            URL string.
        """

    # ── Async variants (override for true async I/O) ──────────────────────────

    async def async_save_file(
        self,
        file_data: Union[bytes, BinaryIO],
        filename: str,
        subfolder: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> StorageFileInfo:
        """Async wrapper around save_file. Override for native async I/O."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.save_file(file_data, filename, subfolder, metadata, **kwargs),
        )

    async def async_get_file(self, identifier: str) -> bytes:
        """Async wrapper around get_file. Override for native async I/O."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.get_file(identifier))

    async def async_delete_file(self, identifier: str) -> bool:
        """Async wrapper around delete_file. Override for native async I/O."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.delete_file(identifier))

    async def async_file_exists(self, identifier: str) -> bool:
        """Async wrapper around file_exists. Override for native async I/O."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.file_exists(identifier))

    async def async_list_files(
        self,
        subfolder: Optional[str] = None,
        pattern: str = "*",
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[StorageFileInfo]:
        """Async wrapper around list_files. Override for native async I/O."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.list_files(subfolder, pattern, limit, **kwargs),
        )

    # ── Convenience methods with default implementations ──────────────────────

    def copy_file(
        self,
        source_identifier: str,
        dest_identifier: str,
        **kwargs,
    ) -> StorageFileInfo:
        """
        Copy a file within storage.

        Default implementation: read + re-save.
        Override in backends that support a native server-side copy
        (e.g. S3 CopyObject) to avoid unnecessary data transfer.
        """
        content     = self.get_file(source_identifier)
        source_info = self.get_file_info(source_identifier)
        return self.save_file(
            content,
            source_info.filename,
            metadata=source_info.metadata,
            **kwargs,
        )

    def move_file(
        self,
        source_identifier: str,
        dest_identifier: str,
        **kwargs,
    ) -> StorageFileInfo:
        """
        Move a file within storage (copy + delete).

        Override in backends that support a native move/rename.
        """
        file_info = self.copy_file(source_identifier, dest_identifier, **kwargs)
        self.delete_file(source_identifier)
        return file_info

    def upload(
        self,
        file_data: Union[bytes, BinaryIO],
        filename: str,
        subfolder: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in: Optional[int] = None,
        **kwargs,
    ) -> StorageUploadResult:
        """
        High-level upload that returns a StorageUploadResult with URL resolved.

        This is the recommended method to call from application code as it
        bundles save + URL generation into one call.
        """
        file_info = self.save_file(file_data, filename, subfolder, metadata, **kwargs)
        url = self.get_file_url(file_info.identifier, expires_in=expires_in)
        return StorageUploadResult(
            file_info=file_info,
            backend=self.backend_type,
            presigned_url=url,
        )

    async def async_upload(
        self,
        file_data: Union[bytes, BinaryIO],
        filename: str,
        subfolder: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in: Optional[int] = None,
        **kwargs,
    ) -> StorageUploadResult:
        """Async version of upload()."""
        file_info = await self.async_save_file(file_data, filename, subfolder, metadata, **kwargs)
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(
            None,
            lambda: self.get_file_url(file_info.identifier, expires_in=expires_in),
        )
        return StorageUploadResult(
            file_info=file_info,
            backend=self.backend_type,
            presigned_url=url,
        )

    def get_storage_info(self) -> Dict[str, Any]:
        """
        Return general information about this backend instance.
        Override to add backend-specific stats (quota, bucket name, etc.).
        """
        return {
            "backend_type": self.backend_type,
            "class":        self.__class__.__name__,
            "capabilities": [
                "save_file",
                "get_file",
                "get_file_info",
                "delete_file",
                "file_exists",
                "list_files",
                "get_file_url",
                "copy_file",
                "move_file",
                "upload",
            ],
        }
    