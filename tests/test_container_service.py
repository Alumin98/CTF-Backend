import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.challenge import DeploymentType
from app.models.challenge_instance import ChallengeInstance
from app.services.container_service import (
    ContainerService,
    InstanceLaunchError,
    InstanceNotAllowed,
    LaunchResult,
)


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commit_count = 0
        self.instances_to_return = []

    def add(self, obj):
        if obj not in self.added:
            self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, obj):
        return obj

    async def commit(self):
        self.commit_count += 1

    async def execute(self, stmt):  # pragma: no cover - patched in tests when needed
        return _FakeResult(self.instances_to_return)


class _FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return _FakeScalarResult(self._items)


class _FakeScalarResult:
    def __init__(self, items):
        self._items = list(items)

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)


def _make_challenge(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=1,
        is_active=True,
        is_private=False,
        docker_image="example:latest",
        visible_from=now - timedelta(minutes=5),
        visible_to=now + timedelta(minutes=5),
        service_url_path="/challenge1/",
        deployment_type=DeploymentType.DYNAMIC_CONTAINER.value,
        always_on=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user(user_id: int = 100) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def test_start_instance_marks_running_and_provides_access_url(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0, base_url="http://access")
        session = _FakeSession()
        challenge = _make_challenge()
        user = _make_user()

        async def _fake_get_latest(*args, **kwargs):
            return None

        async def _fake_launch(**kwargs):
            return LaunchResult(
                container_id="abc123",
                connection_info={"host": "localhost", "ports": [], "path": challenge.service_url_path},
            )

        monkeypatch.setattr(service, "get_latest_active_instance", _fake_get_latest)
        monkeypatch.setattr(service, "_launch_container", _fake_launch)

        instance = await service.start_instance(session, challenge=challenge, user=user)

        assert instance.status == "running"
        assert instance.container_id == "abc123"
        assert instance.connection_info["path"] == challenge.service_url_path
        assert service.build_access_url(challenge=challenge, instance=instance) == "http://access/challenge1/"
        assert session.commit_count == 1

    asyncio.run(_run())


def test_start_instance_reuses_existing(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge()
        user = _make_user()
        existing = ChallengeInstance(challenge_id=challenge.id, user_id=user.id)
        existing.mark_running(container_id="xyz", connection_info={}, started_at=datetime.utcnow(), expires_at=None)

        async def _fake_get_latest(*args, **kwargs):
            return existing

        service._launch_container = AsyncMock()  # type: ignore[attr-defined]
        monkeypatch.setattr(service, "get_latest_active_instance", _fake_get_latest)

        instance = await service.start_instance(session, challenge=challenge, user=user)

        assert instance is existing
        assert not service._launch_container.await_args_list  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_start_instance_raises_when_not_allowed(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge(is_active=False)
        user = _make_user()

        with pytest.raises(InstanceNotAllowed):
            await service.start_instance(session, challenge=challenge, user=user)

    asyncio.run(_run())


def test_start_instance_rejects_static_attachment():
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge(deployment_type=DeploymentType.STATIC_ATTACHMENT.value)
        user = _make_user()

        with pytest.raises(InstanceNotAllowed):
            await service.start_instance(session, challenge=challenge, user=user)

    asyncio.run(_run())


def test_start_instance_records_launch_errors(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge()
        user = _make_user()

        async def _fake_get_latest(*args, **kwargs):
            return None

        async def _boom(**kwargs):
            raise RuntimeError("broken image")

        monkeypatch.setattr(service, "get_latest_active_instance", _fake_get_latest)
        monkeypatch.setattr(service, "_launch_container", _boom)

        with pytest.raises(InstanceLaunchError):
            await service.start_instance(session, challenge=challenge, user=user)

        assert session.commit_count == 1

    asyncio.run(_run())


def test_static_container_creates_shared_instance(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=0, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge(
            deployment_type=DeploymentType.STATIC_CONTAINER.value,
            service_url_path=None,
        )
        user = _make_user()

        async def _fake_launch(**kwargs):
            return LaunchResult(
                container_id="shared",
                connection_info={"host": "localhost", "ports": []},
            )

        async def _fake_get_shared(*args, **kwargs):
            return None

        monkeypatch.setattr(service, "_launch_container", _fake_launch)
        monkeypatch.setattr(service, "get_shared_instance", _fake_get_shared)

        instance = await service.ensure_static_instance(session, challenge=challenge)
        assert instance.user_id is None
        assert instance.status == "running"
        assert session.commit_count == 1

    asyncio.run(_run())


def test_stop_instance_marks_stopped(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        instance = ChallengeInstance(challenge_id=1, user_id=1)
        instance.mark_running(
            container_id="abc",
            connection_info={"ports": []},
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=5),
        )

        async def _noop(container_id):
            return None

        monkeypatch.setattr(service, "_stop_container", _noop)

        stopped = await service.stop_instance(session, instance=instance)

        assert stopped.status == "stopped"
        assert session.commit_count == 1

    asyncio.run(_run())


def test_reap_expired_instances(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        instance = ChallengeInstance(challenge_id=1, user_id=1)
        instance.mark_running(
            container_id="abc",
            connection_info={"ports": []},
            started_at=datetime.utcnow() - timedelta(hours=2),
            expires_at=datetime.utcnow() - timedelta(minutes=5),
        )
        session.instances_to_return = [instance]

        async def _noop(container_id):
            return None

        monkeypatch.setattr(service, "_stop_container", _noop)

        cleaned = await service.reap_expired_instances(session)

        assert cleaned == 1
        assert instance.status == "stopped"

    asyncio.run(_run())


def test_runner_health_when_docker_missing(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        monkeypatch.setattr("app.services.container_service.docker", None)
        result = await service.check_runner_health()
        assert result["status"] == "error"
        assert result["runner"] == service._runner_mode

    asyncio.run(_run())


def test_discover_image_port_uses_exposed_metadata(monkeypatch):
    async def _run():
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)

        async def _fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("app.services.container_service.asyncio.to_thread", _fake_to_thread)

        image = SimpleNamespace(attrs={"Config": {"ExposedPorts": {"8000/tcp": {}, "443/udp": {}}}})
        images = SimpleNamespace(get=lambda name: image, pull=lambda name: image)
        client = SimpleNamespace(images=images)

        port = await service._discover_image_port(client, "example:latest")

        assert port == "8000"

    asyncio.run(_run())


def test_coerce_port_handles_strings_and_numbers():
    service = ContainerService(ttl_seconds=30, cleanup_interval=0)

    assert service._coerce_port(8000) == "8000"
    assert service._coerce_port("8080/tcp") == "8080"
    assert service._coerce_port(" ") is None
    assert service._coerce_port(None) is None


def test_start_instance_blocks_future_visibility():
    async def _run():
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        service = ContainerService(ttl_seconds=30, cleanup_interval=0)
        session = _FakeSession()
        challenge = _make_challenge(visible_from=future)
        user = _make_user()

        with pytest.raises(InstanceNotAllowed):
            await service.start_instance(session, challenge=challenge, user=user)

    asyncio.run(_run())
