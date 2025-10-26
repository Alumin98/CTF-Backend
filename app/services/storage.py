from __future__ import annotations

import asyncio
import os
import pathlib
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from fastapi import HTTPException, UploadFile

from app.models.challenge_attachment import ChallengeAttachment

try:
    import aiofiles
except Exception:  # pragma: no cover - aiofiles should be installed
    aiofiles = None

try:  # optional dependency for S3-compatible stores
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:  # pragma: no cover - boto3 optional
    boto3 = None
    BotoCoreError = ClientError = Exception


@dataclass
class StorageResult:
    backend: str
    path: str
    size: int


class AttachmentStorage:
    backend_name = "base"

    async def save(self, upload: UploadFile) -> StorageResult:  # pragma: no cover - interface only
        raise NotImplementedError

    async def delete(self, attachment: ChallengeAttachment) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    async def open(self, attachment: ChallengeAttachment) -> AsyncIterator[bytes]:  # pragma: no cover
        raise NotImplementedError

    async def signed_url(self, attachment: ChallengeAttachment) -> Optional[str]:
        return None


class LocalAttachmentStorage(AttachmentStorage):
    backend_name = "local"

    def __init__(self, base_path: Optional[str] = None) -> None:
        base_path = base_path or os.getenv("ATTACHMENT_LOCAL_PATH", "storage/attachments")
        self.base_path = pathlib.Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, relative: str) -> pathlib.Path:
        return self.base_path / relative

    async def save(self, upload: UploadFile) -> StorageResult:
        filename = pathlib.Path(upload.filename or "attachment").name
        safe_name = f"{int(asyncio.get_running_loop().time() * 1_000_000)}_{filename}"
        path = self._path_for(safe_name)

        if aiofiles is None:
            data = await upload.read()

            def _write():
                path.write_bytes(data)
                return len(data)

            size = await asyncio.to_thread(_write)
        else:
            size = 0
            async with aiofiles.open(path, "wb") as buffer:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    await buffer.write(chunk)
        await upload.close()
        return StorageResult(backend=self.backend_name, path=safe_name, size=size)

    async def delete(self, attachment: ChallengeAttachment) -> None:
        try:
            self._path_for(attachment.storage_path).unlink()
        except FileNotFoundError:  # pragma: no cover - fine if already gone
            pass

    async def open(self, attachment: ChallengeAttachment) -> AsyncIterator[bytes]:
        file_path = self._path_for(attachment.storage_path)

        async def iterator():
            if aiofiles is None:
                data = await asyncio.to_thread(file_path.read_bytes)
                yield data
            else:
                async with aiofiles.open(file_path, "rb") as handle:
                    while True:
                        chunk = await handle.read(1024 * 256)
                        if not chunk:
                            break
                        yield chunk

        return iterator()


class S3AttachmentStorage(AttachmentStorage):
    backend_name = "s3"

    def __init__(self) -> None:
        if boto3 is None:
            raise RuntimeError("boto3 is required for S3 attachment storage")
        bucket = os.getenv("ATTACHMENT_S3_BUCKET")
        if not bucket:
            raise RuntimeError("ATTACHMENT_S3_BUCKET must be set for S3 storage")
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=os.getenv("ATTACHMENT_S3_ENDPOINT"),
            region_name=os.getenv("ATTACHMENT_S3_REGION"),
        )
        self.ttl = int(os.getenv("ATTACHMENT_S3_URL_TTL", "900"))

    async def save(self, upload: UploadFile) -> StorageResult:
        key = f"{int(asyncio.get_running_loop().time() * 1_000_000)}_{pathlib.Path(upload.filename or 'attachment').name}"

        def _upload():
            self.client.upload_fileobj(upload.file, self.bucket, key)

        try:
            await asyncio.to_thread(_upload)
        except (BotoCoreError, ClientError) as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Failed to store attachment: {exc}") from exc
        size = upload.file.tell()
        await upload.close()
        return StorageResult(backend=self.backend_name, path=key, size=size)

    async def delete(self, attachment: ChallengeAttachment) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=attachment.storage_path)

    async def open(self, attachment: ChallengeAttachment) -> AsyncIterator[bytes]:  # pragma: no cover - not used
        raise HTTPException(status_code=400, detail="Use signed URLs for S3 attachments")

    async def signed_url(self, attachment: ChallengeAttachment) -> Optional[str]:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": attachment.storage_path},
            ExpiresIn=self.ttl,
        )


_storage: Optional[AttachmentStorage] = None


def get_attachment_storage() -> AttachmentStorage:
    global _storage
    if _storage is not None:
        return _storage

    backend = os.getenv("ATTACHMENT_STORAGE", "local").lower()
    if backend == "local":
        _storage = LocalAttachmentStorage()
    elif backend == "s3":
        _storage = S3AttachmentStorage()
    else:  # pragma: no cover - configuration error
        raise RuntimeError(f"Unsupported ATTACHMENT_STORAGE backend: {backend}")
    return _storage
