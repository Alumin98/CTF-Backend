from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge
from app.models.challenge_instance import ChallengeInstance

try:
    import docker
    from docker.errors import DockerException
except Exception:  # pragma: no cover - the docker package may be missing in tests
    docker = None

    class DockerException(Exception):
        pass


_LOGGER = logging.getLogger(__name__)


class ContainerService:
    """Thin wrapper around the Docker SDK used for dynamic challenge instances."""

    def __init__(
        self,
        *,
        ttl_seconds: int = None,
        cleanup_interval: int = None,
        docker_host_label: Optional[str] = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds or int(os.getenv("CHALLENGE_INSTANCE_TIMEOUT", "3600"))
        self.cleanup_interval = cleanup_interval or int(os.getenv("CHALLENGE_INSTANCE_CLEANUP_INTERVAL", "60"))
        self.docker_network = os.getenv("CHALLENGE_CONTAINER_NETWORK") or None
        self.docker_host_label = docker_host_label or os.getenv("CHALLENGE_CONTAINER_HOST", "localhost")
        self._cleanup_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Docker helpers
    # ------------------------------------------------------------------
    def _client(self):
        if docker is None:
            raise RuntimeError(
                "docker SDK is not installed. Install the 'docker' package to use container instances."
            )
        return docker.from_env()

    async def _run_in_thread(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def start_container(
        self,
        *,
        instance: ChallengeInstance,
        challenge: Challenge,
    ) -> dict[str, Any]:
        if not challenge.docker_image:
            raise RuntimeError("Challenge is missing a docker_image configuration")

        client = self._client()
        labels = {
            "ctf.challenge_id": str(challenge.id),
            "ctf.user_id": str(instance.user_id),
        }

        options: Dict[str, Any] = {
            "detach": True,
            "auto_remove": False,
            "labels": labels,
        }
        if self.docker_network:
            options["network"] = self.docker_network

        container = await self._run_in_thread(
            client.containers.run,
            challenge.docker_image,
            **options,
        )

        await self._run_in_thread(container.reload)
        info = container.attrs or {}
        ports = info.get("NetworkSettings", {}).get("Ports", {})
        host = self.docker_host_label
        mapped_ports: list[dict[str, Any]] = []
        for container_port, binding in ports.items():
            if not binding:
                continue
            mapped_ports.append(
                {
                    "container_port": container_port,
                    "host": binding[0].get("HostIp", host),
                    "host_port": binding[0].get("HostPort"),
                }
            )

        return {
            "container_id": container.id,
            "connection": {
                "host": host,
                "ports": mapped_ports,
            },
        }

    async def stop_container(self, *, container_id: str) -> None:
        if not container_id:
            return
        client = self._client()
        try:
            container = await self._run_in_thread(client.containers.get, container_id)
        except DockerException as exc:  # pragma: no cover - depends on docker availability
            _LOGGER.warning("Unable to locate container %s: %s", container_id, exc)
            return
        await self._run_in_thread(container.stop)

    # ------------------------------------------------------------------
    # High-level orchestration
    # ------------------------------------------------------------------
    async def provision_instance(
        self,
        *,
        session: AsyncSession,
        instance: ChallengeInstance,
        challenge: Challenge,
    ) -> ChallengeInstance:
        try:
            result = await self.start_container(instance=instance, challenge=challenge)
        except Exception as exc:  # pragma: no cover - error path is deterministic
            _LOGGER.exception("Failed to start container for challenge %s", challenge.id)
            instance.mark_error(str(exc))
        else:
            started_at = datetime.now(timezone.utc)
            expires_at = started_at + timedelta(seconds=self.ttl_seconds) if self.ttl_seconds else None
            instance.mark_running(
                container_id=result.get("container_id"),
                connection_info=result.get("connection"),
                started_at=started_at,
                expires_at=expires_at,
            )
        finally:
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
        return instance

    async def terminate_instance(self, *, session: AsyncSession, instance: ChallengeInstance) -> ChallengeInstance:
        try:
            await self.stop_container(container_id=instance.container_id)
        except Exception as exc:  # pragma: no cover - depends on docker availability
            _LOGGER.warning("Failed stopping container %s: %s", instance.container_id, exc)
        instance.mark_stopped()
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
        return instance

    async def cleanup_once(self, *, session: AsyncSession) -> int:
        stmt = select(ChallengeInstance).where(
            ChallengeInstance.status == "running",
            ChallengeInstance.expires_at.isnot(None),
            ChallengeInstance.expires_at < datetime.now(timezone.utc),
        )
        result = await session.execute(stmt)
        expired = result.scalars().all()
        count = 0
        for inst in expired:
            await self.terminate_instance(session=session, instance=inst)
            count += 1
        return count

    async def start_cleanup_task(self, session_factory) -> None:
        if self.cleanup_interval <= 0:
            return
        if self._cleanup_task:
            return

        async def _loop():
            while True:
                try:
                    async with session_factory() as session:
                        await self.cleanup_once(session=session)
                except asyncio.CancelledError:  # pragma: no cover - controlled by shutdown
                    raise
                except Exception as exc:  # pragma: no cover - defensive logging
                    _LOGGER.exception("Container cleanup failed: %s", exc)
                await asyncio.sleep(self.cleanup_interval)

        self._cleanup_task = asyncio.create_task(_loop())

    async def stop_cleanup_task(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:  # pragma: no cover
                pass
            finally:
                self._cleanup_task = None


_service: Optional[ContainerService] = None


def get_container_service() -> ContainerService:
    global _service
    if _service is None:
        _service = ContainerService()
    return _service
