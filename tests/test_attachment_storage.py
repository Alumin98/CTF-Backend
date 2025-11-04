import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.models.challenge_attachment import ChallengeAttachment
from app.services.storage import LocalAttachmentStorage


def test_local_storage_roundtrip(tmp_path: Path):
    async def _run():
        storage_path = tmp_path / "attachments"
        storage = LocalAttachmentStorage(base_path=str(storage_path))

        upload = UploadFile(filename="note.txt", file=BytesIO(b"hello world"))
        result = await storage.save(7, upload)

        assert result.backend == "local"
        saved_path = storage_path / result.path
        assert saved_path.exists()
        assert str(result.path).startswith("7/")

        attachment = ChallengeAttachment(
            id=1,
            challenge_id=7,
            filename="note.txt",
            content_type="text/plain",
            storage_backend=result.backend,
            storage_path=result.path,
            filesize=result.size,
        )

        chunks = []
        async for chunk in await storage.open(attachment):
            chunks.append(chunk)

        assert b"".join(chunks) == b"hello world"

        resolved = storage.get_file_path(attachment)
        assert resolved.exists()

        await storage.delete(attachment)
        assert not resolved.exists()
        assert not saved_path.exists()

    asyncio.run(_run())
