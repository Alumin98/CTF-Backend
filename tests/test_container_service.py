import asyncio
from types import SimpleNamespace

from app.models.challenge_instance import ChallengeInstance
from app.services.containers import ContainerService


class _FakeSession:
    def __init__(self):
        self.commit_count = 0
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, obj):
        return obj


def test_provision_instance_marks_running(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)

        async def _fake_start_container(**kwargs):
            return {"container_id": "abc123", "connection": {"host": "localhost", "ports": []}}

        monkeypatch.setattr(service, "start_container", _fake_start_container)

        session = _FakeSession()
        instance = ChallengeInstance(challenge_id=1, user_id=10)
        challenge = SimpleNamespace(id=1, docker_image="example:latest")

        result = await service.provision_instance(session=session, instance=instance, challenge=challenge)

        assert result.status == "running"
        assert result.container_id == "abc123"
        assert result.connection_info["host"] == "localhost"
        assert session.commit_count == 1

    asyncio.run(_run())


def test_provision_instance_records_error(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)

        async def _boom(**kwargs):
            raise RuntimeError("unable to start")

        monkeypatch.setattr(service, "start_container", _boom)

        session = _FakeSession()
        instance = ChallengeInstance(challenge_id=1, user_id=10)
        challenge = SimpleNamespace(id=1, docker_image="example:latest")

        result = await service.provision_instance(session=session, instance=instance, challenge=challenge)

        assert result.status == "error"
        assert "unable to start" in result.error_message
        assert session.commit_count == 1

    asyncio.run(_run())
