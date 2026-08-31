"""Centralized invoice-file storage abstraction.

Backed by ``settings.STORAGE_BACKEND``:
  local — files live under ATTACHMENT_DIR on local disk (default, unchanged
          behavior from before this module existed).
  s3    — files live in an S3 bucket. Requires ``S3_BUCKET_NAME`` to be
          configured. Credentials come from the standard boto3 default
          credential chain (IAM instance role in production — no access
          keys are configured in this app).

(``google_drive`` is a secondary best-effort *mirror* of the primary file,
handled separately by ``app/services/drive_upload.py`` — it never changes
where the primary/authoritative copy lives, so it is not part of this
module's local/s3 branching.)

DB ``file_path`` column convention (the column is already a generic
``String(500)`` — no migration needed):
  local — a local filesystem path, exactly as before (e.g.
          ``data/attachments/<msg_id>/<filename>``).
  s3    — an ``s3://<bucket>/<key>`` URI (e.g.
          ``s3://my-bucket/attachments/12/<msg_id>/<filename>``). The
          ``s3://`` scheme makes the storage backend unambiguous from the
          value alone, so callers never need to consult STORAGE_BACKEND to
          know how to interpret an existing file_path.

Every call site that reads/writes an invoice file should go through the
functions below instead of calling ``open()`` / ``os.path`` directly, so the
local-vs-S3 branching lives in exactly one place.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
from typing import Callable, Iterator, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_S3_URI_RE = re.compile(r"^s3://([^/]+)/(.+)$")
_FILENAME_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]")


class StorageError(RuntimeError):
    """Raised for storage-backend configuration/operational failures."""


def _sanitize_filename(name: str) -> str:
    """Reuse the repo-wide filename sanitization convention (see adhoc_routes.py)."""
    return _FILENAME_SAFE_RE.sub("_", name or "file")


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise StorageError(
            "STORAGE_BACKEND=s3 requires the boto3 package. Run: pip install boto3"
        ) from exc
    return boto3.client("s3", region_name=settings.S3_REGION)


def is_remote(file_path: str) -> bool:
    """True if file_path is an s3:// URI (regardless of current STORAGE_BACKEND)."""
    return bool(file_path) and file_path.startswith("s3://")


def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    m = _S3_URI_RE.match(uri)
    if not m:
        raise StorageError(f"Not a valid s3:// URI: {uri}")
    return m.group(1), m.group(2)


def save(company_id, filename: str, content: bytes, subdir: str = "") -> str:
    """Persist `content` under the active storage backend.

    Returns the value to store in the DB `file_path` column. `subdir` (e.g. a
    Gmail message id, or "adhoc") is nested under the backend's namespace —
    for local this mirrors the pre-existing directory layout exactly; for s3
    it sits under an ``attachments/{company_id}/`` prefix so a shared bucket
    stays tenant-isolated at a glance.
    """
    safe_name = _sanitize_filename(filename)

    if settings.STORAGE_BACKEND == "s3":
        if not settings.S3_BUCKET_NAME:
            raise StorageError("STORAGE_BACKEND=s3 but S3_BUCKET_NAME is not configured")
        key_parts = ["attachments", str(company_id or "unknown")]
        if subdir:
            key_parts.append(subdir)
        key_parts.append(safe_name)
        key = "/".join(key_parts)
        _s3_client().put_object(Bucket=settings.S3_BUCKET_NAME, Key=key, Body=content)
        uri = f"s3://{settings.S3_BUCKET_NAME}/{key}"
        logger.info("Saved attachment to S3: %s (%d bytes)", uri, len(content))
        return uri

    # local (default) — unchanged from pre-existing behavior
    dest_dir = os.path.join(settings.ATTACHMENT_DIR, subdir) if subdir else settings.ATTACHMENT_DIR
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_name)
    with open(dest_path, "wb") as f:
        f.write(content)
    return dest_path


def write_bytes(file_path: str, content: bytes) -> None:
    """Overwrite the existing local path or s3:// URI with new content in place.

    Used for recovery flows (e.g. re-downloading from Gmail into the same
    file_path already stored on the DB record).
    """
    if is_remote(file_path):
        bucket, key = _parse_s3_uri(file_path)
        _s3_client().put_object(Bucket=bucket, Key=key, Body=content)
        return
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(content)


def exists(file_path: str) -> bool:
    if not file_path:
        return False
    if is_remote(file_path):
        bucket, key = _parse_s3_uri(file_path)
        try:
            _s3_client().head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return os.path.exists(file_path)


def delete(file_path: str) -> None:
    """Best-effort delete — logs and swallows failures, never raises."""
    if not file_path:
        return
    if is_remote(file_path):
        bucket, key = _parse_s3_uri(file_path)
        try:
            _s3_client().delete_object(Bucket=bucket, Key=key)
        except Exception as exc:
            logger.warning("Failed to delete S3 object %s: %s", file_path, exc)
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError as exc:
        logger.warning("Failed to delete local file %s: %s", file_path, exc)


def download_to_temp(file_path: str) -> Tuple[str, Callable[[], None]]:
    """Download an s3:// URI to a fresh temp file. Returns (local_path, cleanup).

    Uses `tempfile` (not a fixed path) so this is safe under concurrent
    requests. Caller MUST call cleanup() (typically in a `finally` block) to
    remove the temp file.
    """
    bucket, key = _parse_s3_uri(file_path)
    suffix = os.path.splitext(key)[1] or ""
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="attachment_")
    os.close(fd)
    try:
        _s3_client().download_file(bucket, key, tmp_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    def cleanup() -> None:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return tmp_path, cleanup


@contextlib.contextmanager
def open_for_read(file_path: str) -> Iterator[str]:
    """Yield a local filesystem path usable with plain `open()`/file-path APIs.

    For a local file_path this yields it unchanged (no copy, no cleanup). For
    an s3:// URI this downloads to a temp file first and removes it again on
    exit — safe under concurrent requests since each call gets its own
    tempfile.

    Usage:
        with attachment_storage.open_for_read(record.file_path) as local_path:
            do_something_with_local_file(local_path)
    """
    if is_remote(file_path):
        local_path, cleanup = download_to_temp(file_path)
        try:
            yield local_path
        finally:
            cleanup()
    else:
        yield file_path


def read_bytes(file_path: str) -> bytes:
    """Read the full content of file_path (local or s3://) into memory."""
    if is_remote(file_path):
        bucket, key = _parse_s3_uri(file_path)
        obj = _s3_client().get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    with open(file_path, "rb") as f:
        return f.read()


def _delete_s3_prefix(prefix: str) -> int:
    client = _s3_client()
    deleted = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not keys:
                continue
            client.delete_objects(Bucket=settings.S3_BUCKET_NAME, Delete={"Objects": keys})
            deleted += len(keys)
    except Exception as exc:
        logger.warning("Failed to delete S3 prefix %s: %s", prefix, exc)
    return deleted


def delete_prefix(company_id) -> int:
    """Delete every S3 object under this company's attachment prefix.

    No-op (returns 0) unless STORAGE_BACKEND is s3 — local attachment
    cleanup for a company is handled separately (shutil.rmtree on its local
    directory), since that path predates this module and stays unchanged.
    """
    if settings.STORAGE_BACKEND != "s3" or not settings.S3_BUCKET_NAME:
        return 0
    return _delete_s3_prefix(f"attachments/{company_id}/")


def delete_all() -> int:
    """Delete every S3 object under the shared "attachments/" prefix (all
    companies). No-op (returns 0) unless STORAGE_BACKEND is s3.
    """
    if settings.STORAGE_BACKEND != "s3" or not settings.S3_BUCKET_NAME:
        return 0
    return _delete_s3_prefix("attachments/")
