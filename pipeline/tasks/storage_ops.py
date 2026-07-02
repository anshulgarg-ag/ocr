"""
Backend-agnostic storage operations via fsspec.

Set STORAGE_ROOT env var to change backend:
  s3://bucket        → MinIO or AWS S3 (set MINIO_ENDPOINT for self-hosted)
  gs://bucket        → Google Cloud Storage
  az://container     → Azure Blob Storage
  file:///mnt/data   → local filesystem

All callers pass only relative paths (e.g. "raw/doc.pdf").
This module prepends STORAGE_ROOT and constructs the fsspec URL.
"""
import hashlib
import io
from pathlib import PurePosixPath

import fsspec

from config.logging import get_logger
from config.settings import settings

log = get_logger(__name__)

_fs_cache: dict[str, fsspec.AbstractFileSystem] = {}


def _get_fs() -> tuple[fsspec.AbstractFileSystem, str]:
    root = settings.storage_root
    protocol = root.split("://")[0] if "://" in root else "file"
    base = root

    if protocol not in _fs_cache:
        if protocol == "s3":
            import s3fs

            _fs_cache[protocol] = s3fs.S3FileSystem(
                key=settings.minio_access_key,
                secret=settings.minio_secret_key,
                client_kwargs={"endpoint_url": settings.minio_endpoint},
            )
        else:
            _fs_cache[protocol] = fsspec.filesystem(protocol)

    return _fs_cache[protocol], base


def _full_path(relative: str) -> str:
    fs, base = _get_fs()
    return str(PurePosixPath(base) / relative)


def upload(local_path: str, relative_dest: str) -> str:
    """Upload a local file to storage. Returns the full storage path."""
    fs, _ = _get_fs()
    dest = _full_path(relative_dest)
    fs.put(local_path, dest)
    log.debug("storage_upload", src=local_path, dest=dest)
    return dest


def upload_bytes(data: bytes, relative_dest: str) -> str:
    """Upload raw bytes to storage. Returns the full storage path."""
    fs, _ = _get_fs()
    dest = _full_path(relative_dest)
    with fs.open(dest, "wb") as f:
        f.write(data)
    return dest


def download(relative_src: str, local_path: str) -> None:
    """Download a file from storage to a local path."""
    fs, _ = _get_fs()
    src = _full_path(relative_src)
    fs.get(src, local_path)
    log.debug("storage_download", src=src, dest=local_path)


def read_bytes(relative_src: str) -> bytes:
    """Read a file from storage into memory."""
    fs, _ = _get_fs()
    src = _full_path(relative_src)
    with fs.open(src, "rb") as f:
        return f.read()


def read_text(relative_src: str, encoding: str = "utf-8") -> str:
    return read_bytes(relative_src).decode(encoding)


def write_text(content: str, relative_dest: str, encoding: str = "utf-8") -> str:
    return upload_bytes(content.encode(encoding), relative_dest)


def list_files(relative_prefix: str, extensions: tuple[str, ...] = ()) -> list[str]:
    """List files under a prefix. Returns relative paths."""
    fs, base = _get_fs()
    prefix = _full_path(relative_prefix)
    try:
        all_paths = fs.ls(prefix, detail=False)
    except FileNotFoundError:
        return []
    base_len = len(base.rstrip("/")) + 1
    relative = [p[base_len:] for p in all_paths if not fs.isdir(p)]
    if extensions:
        relative = [p for p in relative if any(p.lower().endswith(e) for e in extensions)]
    return relative


def etag(relative_path: str) -> str:
    """Return a content hash for deduplication. Uses S3 ETag if available, else SHA-256."""
    fs, _ = _get_fs()
    path = _full_path(relative_path)
    try:
        info = fs.info(path)
        if "ETag" in info:
            return info["ETag"].strip('"')
    except Exception:
        pass
    # Fallback: SHA-256 of content
    data = read_bytes(relative_path)
    return hashlib.sha256(data).hexdigest()


def exists(relative_path: str) -> bool:
    fs, _ = _get_fs()
    return fs.exists(_full_path(relative_path))


def ensure_bucket() -> None:
    """Create the storage root bucket/prefix if it doesn't exist."""
    fs, base = _get_fs()
    try:
        if not fs.exists(base):
            fs.mkdir(base, create_parents=True)
            log.info("storage_bucket_created", path=base)
    except Exception as exc:
        log.warning("storage_bucket_ensure_failed", error=str(exc))
