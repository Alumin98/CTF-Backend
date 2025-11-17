import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
    def __init__(self, instances=None):
        self.added = []
        self.commit_count = 0
        self._result_instances = instances or []

    def add(self, obj):
        if obj not in self.added:
            self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, obj):
        return obj

    async def commit(self):
        self.commit_count += 1

    async def execute(self, stmt):
        return _FakeResult(self._result_instances)


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
        deployment_type=DeploymentType.dynamic_container,
        always_on=False,
        service_port=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user(user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def test_start_instance_marks_running(monkeypatch):
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
        assert service.build_access_url(challenge=challenge, instance=instance) == "http://access/challenge1/"
        assert session.commit_count == 1

    asyncio.run(_run())


def test_ensure_static_instance_reuses_running(monkeypatch):
    async def _run():
        challenge = _make_challenge(deployment_type=DeploymentType.static_container)
        service = ContainerService(ttl_seconds=0, cleanup_interval=0)
        existing = ChallengeInstance(challenge_id=challenge.id, user_id=None)
        existing.mark_running(
            container_id="shared",
            connection_info={"host": "localhost", "ports": []},
            started_at=datetime.now(timezone.utc),
            expires_at=None,
        )
        session = _FakeSession(instances=[existing])

        async def _fake_launch(**kwargs):  # pragma: no cover - should not run
            raise AssertionError("launch should not be called")

        monkeypatch.setattr(service, "_launch_container", _fake_launch)

        instance = await service.ensure_static_instance(session, challenge=challenge)
        assert instance is existing

    asyncio.run(_run())


def test_build_access_url_uses_host_port():
    service = ContainerService()
    challenge = _make_challenge(service_url_path=None)
    user = _make_user()
    instance = ChallengeInstance(challenge_id=challenge.id, user_id=user.id)
    instance.mark_running(
        container_id="abc",
        connection_info={
            "host": "localhost",
            "ports": [
                {"host": "localhost", "host_port": "55492", "container_port": "8000/tcp"}
            ],
        },
        started_at=datetime.now(timezone.utc),
        expires_at=None,
    )

    url = service.build_access_url(challenge=challenge, instance=instance)
    assert url == "http://localhost:55492/"


def test_coerce_port_variants():
    service = ContainerService()
    assert service._coerce_port("8000/tcp") == "8000"
    assert service._coerce_port("443") == "443"
    assert service._coerce_port(1234) == "1234"
    assert service._coerce_port("invalid") is None
    assert service._coerce_port(0) is None


def test_discover_image_port_prefers_hints(monkeypatch):
    service = ContainerService()
    challenge = _make_challenge(service_port=5000, service_url_path=None)
    fake_client = SimpleNamespace(images=None)

    port = service._discover_image_port(fake_client, challenge)
    assert port == "5000"


def test_discover_image_port_uses_image_metadata(monkeypatch):
    service = ContainerService()
    challenge = _make_challenge(service_port=None, service_url_path=None)

    class _FakeImages:
        def get(self, name):
            assert name == challenge.docker_image
            return SimpleNamespace(attrs={"Config": {"ExposedPorts": {"7777/tcp": {}}}})

    fake_client = SimpleNamespace(images=_FakeImages())

    port = service._discover_image_port(fake_client, challenge)
    assert port == "7777"


def test_start_instance_rejects_static_attachment():
    async def _run():
        service = ContainerService()
        session = _FakeSession()
        challenge = _make_challenge(deployment_type=DeploymentType.static_attachment)
        user = _make_user()

        with pytest.raises(InstanceNotAllowed):
            await service.start_instance(session, challenge=challenge, user=user)

    asyncio.run(_run())


def test_launch_error_marks_instance(monkeypatch):
    async def _run():
        service = ContainerService()
        session = _FakeSession()
        challenge = _make_challenge()
        user = _make_user()

        async def _fake_launch(**kwargs):
            raise RuntimeError("no docker")

        monkeypatch.setattr(service, "_launch_container", _fake_launch)

        async def _fake_get_latest(*args, **kwargs):
            return None

        monkeypatch.setattr(service, "get_latest_active_instance", _fake_get_latest)

        with pytest.raises(InstanceLaunchError):
            await service.start_instance(session, challenge=challenge, user=user)

    asyncio.run(_run())
