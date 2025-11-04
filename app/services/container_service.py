from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge
from app.models.challenge_instance import ChallengeInstance
from app.models.user import User

try:  # pragma: no cover - docker is optional in some test environments
    import docker
    from docker.errors import DockerException
except Exception:  # pragma: no cover - fallback when docker isn't installed
    docker = None

    class DockerException(Exception):
        pass


_LOGGER = logging.getLogger(__name__)


class InstanceError(Exception):
    """Base error for container instance lifecycle issues."""


class InstanceNotAllowed(InstanceError):
    """Raised when a challenge cannot launch an instance."""


class InstanceLaunchError(InstanceError):
    """Raised when Docker fails to provision an instance."""


@dataclass(slots=True)
class LaunchResult:
    container_id: str
    connection_info: dict[str, Any]


class ContainerService:
    """Provision and manage per-user Docker challenge instances."""

    def __init__(
        self,
        *,
        ttl_seconds: Optional[int] = None,
        cleanup_interval: Optional[int] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds or int(os.getenv("CHALLENGE_INSTANCE_TIMEOUT", "3600"))
        self.cleanup_interval = cleanup_interval or int(
            os.getenv("CHALLENGE_INSTANCE_CLEANUP_INTERVAL", "60")
        )
        configured_base = (base_url or os.getenv("CHALLENGE_ACCESS_BASE_URL", "")).strip()
        self._base_url = configured_base.rstrip("/")
        parsed = urlparse(configured_base) if configured_base else None
        self._base_scheme = parsed.scheme if parsed and parsed.scheme else "http"
        self._base_host = parsed.hostname if parsed else None
        self._base_port = parsed.port if parsed else None

        preferred_network = os.getenv("CHALLENGE_CONTAINER_NETWORK")
        self._preferred_networks = [preferred_network] if preferred_network else []
        if "ctf_net" not in self._preferred_networks:
            self._preferred_networks.append("ctf_net")
        self._resolved_network: Optional[str] = None
        self._network_checked = False
        self._cleanup_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def start_instance(
        self,
        db: AsyncSession,
        *,
        challenge: Challenge,
        user: User,
    ) -> ChallengeInstance:
        """Start (or reuse) an active instance for the user."""

        self._ensure_launchable(challenge)

        existing = await self.get_latest_active_instance(
            db, challenge_id=challenge.id, user_id=user.id
        )
        if existing:
            return existing

        instance = ChallengeInstance(challenge_id=challenge.id, user_id=user.id)
        instance.mark_starting()
        db.add(instance)
        await db.flush()
        await db.refresh(instance)

        try:
            launch = await self._launch_container(challenge=challenge, instance=instance, user=user)
        except Exception as exc:  # pragma: no cover - depends on docker availability
            message = str(exc)
            instance.mark_error(message)
            db.add(instance)
            await db.commit()
            await db.refresh(instance)
            raise InstanceLaunchError(message) from exc

        started_at = datetime.utcnow()
        expires_at = (
            started_at + timedelta(seconds=self.ttl_seconds)
            if self.ttl_seconds
            else None
        )
        instance.mark_running(
            container_id=launch.container_id,
            connection_info=launch.connection_info,
            started_at=started_at,
            expires_at=expires_at,
        )
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
        return instance

    async def stop_instance(
        self,
        db: AsyncSession,
        *,
        instance: ChallengeInstance,
    ) -> ChallengeInstance:
        """Stop the Docker container backing an instance."""

        if instance.status != "stopped":
            try:
                await self._stop_container(instance.container_id)
            except Exception as exc:  # pragma: no cover - defensive logging
                _LOGGER.warning("Failed stopping container %s: %s", instance.container_id, exc)
        instance.mark_stopped()
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
        return instance

    async def get_latest_active_instance(
        self,
        db: AsyncSession,
        *,
        challenge_id: int,
        user_id: int,
    ) -> Optional[ChallengeInstance]:
        stmt = (
            select(ChallengeInstance)
            .where(
                ChallengeInstance.challenge_id == challenge_id,
                ChallengeInstance.user_id == user_id,
                ChallengeInstance.status.in_(ChallengeInstance.ACTIVE_STATUSES),
            )
            .order_by(ChallengeInstance.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        instance = result.scalars().first()
        if not instance:
            return None
        if instance.is_expired():
            await self.stop_instance(db, instance=instance)
            return None
        return instance

    async def reap_expired_instances(self, db: AsyncSession) -> int:
        """Stop expired instances and return the number cleaned up."""

        now = datetime.utcnow()
        stmt = (
            select(ChallengeInstance)
            .where(
                ChallengeInstance.status.in_(ChallengeInstance.ACTIVE_STATUSES),
                ChallengeInstance.expires_at.isnot(None),
                ChallengeInstance.expires_at < now,
            )
        )
        result = await db.execute(stmt)
        expired = result.scalars().all()
        count = 0
        for instance in expired:
            await self.stop_instance(db, instance=instance)
            count += 1
        return count

    async def start_cleanup_task(self, session_factory) -> None:
        if self.cleanup_interval <= 0 or self._cleanup_task:
            return

        async def _loop():
            while True:
                try:
                    async with session_factory() as db:
                        await self.reap_expired_instances(db)
                except asyncio.CancelledError:  # pragma: no cover - task cancelled intentionally
                    raise
                except Exception as exc:  # pragma: no cover - defensive logging
                    _LOGGER.exception("Challenge instance cleanup failed: %s", exc)
                await asyncio.sleep(self.cleanup_interval)

        self._cleanup_task = asyncio.create_task(_loop())

    async def stop_cleanup_task(self) -> None:
        if not self._cleanup_task:
            return
        self._cleanup_task.cancel()
        try:
            await self._cleanup_task
        except asyncio.CancelledError:  # pragma: no cover - expected during shutdown
            pass
        finally:
            self._cleanup_task = None

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------
    def build_access_url(
        self,
        *,
        challenge: Challenge,
        instance: Optional[ChallengeInstance] = None,
    ) -> Optional[str]:
        path = getattr(challenge, "service_url_path", None)
        if path:
            path = path if path.startswith("/") else f"/{path}"
            if self._base_url:
                return urljoin(f"{self._base_url}/", path.lstrip("/"))
            return path

        if instance is None:
            return None

        info = instance.connection_info or {}
        ports = info.get("ports") or []
        if ports:
            binding = ports[0]
            host = binding.get("host") or info.get("host") or self._base_host or "localhost"
            host = host if host not in {"0.0.0.0", ""} else (self._base_host or "localhost")
            port = binding.get("host_port") or binding.get("port")
            scheme = self._base_scheme or "http"
            if self._base_host and host == "localhost":
                host = self._base_host
            netloc = host
            if port:
                netloc = f"{host}:{port}"
            elif self._base_port and host == (self._base_host or host):
                netloc = f"{host}:{self._base_port}"
            return urlunparse((scheme, netloc, "/", "", ""))

        if self._base_url:
            return self._base_url
        return None

    # ------------------------------------------------------------------
    # Docker helpers
    # ------------------------------------------------------------------
    async def _launch_container(
        self,
        *,
        challenge: Challenge,
        instance: ChallengeInstance,
        user: User,
    ) -> LaunchResult:
        if docker is None:
            raise RuntimeError("Docker SDK is not available. Install the 'docker' package to continue.")

        client = await asyncio.to_thread(docker.from_env)
        try:
            network = await self._resolve_network(client)
            labels = {
                "ctf.challenge_id": str(challenge.id),
                "ctf.user_id": str(user.id),
                "ctf.instance_id": str(instance.id),
            }
            name = f"ctf_{challenge.id}_{user.id}_{int(time.time())}"

            options: dict[str, Any] = {
                "detach": True,
                "auto_remove": False,
                "labels": labels,
                "name": name,
            }
            if network:
                options["network"] = network

            service_path = getattr(challenge, "service_url_path", None)
            if not service_path:
                container_port = (
                    getattr(challenge, "service_port", None)
                    or getattr(challenge, "service_internal_port", None)
                    or getattr(challenge, "internal_port", None)
                    or 80
                )
                options["ports"] = {f"{container_port}/tcp": None}

            container = await asyncio.to_thread(
                client.containers.run,
                challenge.docker_image,
                **options,
            )

            await asyncio.to_thread(container.reload)
            info = container.attrs or {}
            network_settings = info.get("NetworkSettings", {})
            ports_info = network_settings.get("Ports", {})
            mapped: list[dict[str, Any]] = []
            for container_port, bindings in (ports_info or {}).items():
                if not bindings:
                    continue
                for binding in bindings:
                    mapped.append(
                        {
                            "container_port": container_port,
                            "host": binding.get("HostIp") or self._base_host or "localhost",
                            "host_port": binding.get("HostPort"),
                        }
                    )

            connection = {
                "host": self._base_host or "localhost",
                "ports": mapped,
            }
            if service_path:
                connection["path"] = service_path
            if network:
                connection["network"] = network

            return LaunchResult(container_id=container.id, connection_info=connection)
        finally:  # pragma: no cover - closing client is best effort
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                pass

    async def _stop_container(self, container_id: Optional[str]) -> None:
        if not container_id:
            return
        if docker is None:
            return
        client = await asyncio.to_thread(docker.from_env)
        try:
            try:
                container = await asyncio.to_thread(client.containers.get, container_id)
            except DockerException as exc:
                _LOGGER.warning("Container %s not found: %s", container_id, exc)
                return
            await asyncio.to_thread(container.stop)
            await asyncio.to_thread(container.remove, force=True)
        finally:  # pragma: no cover
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                pass

    async def _resolve_network(self, client) -> Optional[str]:
        if self._network_checked:
            return self._resolved_network

        for candidate in self._preferred_networks:
            if not candidate:
                continue
            try:
                await asyncio.to_thread(client.networks.get, candidate)
            except DockerException:
                continue
            else:
                self._resolved_network = candidate
                break

        self._network_checked = True
        return self._resolved_network

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _ensure_launchable(self, challenge: Challenge) -> None:
        if not challenge.is_active or getattr(challenge, "is_private", False):
            raise InstanceNotAllowed("Challenge is not active")
        if not challenge.docker_image:
            raise InstanceNotAllowed("Challenge does not have a docker image configured")

        now = datetime.now(timezone.utc)
        start = getattr(challenge, "visible_from", None)
        if start:
            start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
            if now < start:
                raise InstanceNotAllowed("Challenge is not yet visible")
        end = getattr(challenge, "visible_to", None)
        if end:
            end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            if now > end:
                raise InstanceNotAllowed("Challenge is no longer visible")


_service: Optional[ContainerService] = None


def get_container_service() -> ContainerService:
    global _service
    if _service is None:
        _service = ContainerService()
    return _service
