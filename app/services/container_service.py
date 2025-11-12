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

from app.models.challenge import Challenge, DeploymentType
from app.models.challenge_instance import ChallengeInstance
from app.models.user import User

try:  # pragma: no cover - docker is optional in some test environments
    import docker
    from docker.errors import DockerException
    try:
        from docker.tls import TLSConfig
    except Exception:  # pragma: no cover - TLS helpers optional
        TLSConfig = None
except Exception:  # pragma: no cover - fallback when docker isn't installed
    docker = None
    TLSConfig = None

    class DockerException(Exception):
        pass


_LOGGER = logging.getLogger(__name__)


class _SystemUser:
    id = 0


_SYSTEM_USER = _SystemUser()


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
        self._runner_mode = (os.getenv("CHALLENGE_RUNNER", "local") or "local").lower()

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

        deployment = getattr(challenge, "deployment_type", DeploymentType.STATIC_ATTACHMENT.value)

        if deployment == DeploymentType.STATIC_ATTACHMENT.value:
            raise InstanceNotAllowed("Challenge provides downloadable attachments only")

        self._ensure_launchable(
            challenge,
            require_docker_image=deployment in {
                DeploymentType.DYNAMIC_CONTAINER.value,
                DeploymentType.STATIC_CONTAINER.value,
            },
        )

        if deployment == DeploymentType.STATIC_CONTAINER.value:
            return await self.ensure_static_instance(db, challenge=challenge)

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
            launch = await self._launch_container(
                challenge=challenge,
                instance=instance,
                user=user,
            )
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

    async def get_shared_instance(
        self,
        db: AsyncSession,
        *,
        challenge_id: int,
    ) -> Optional[ChallengeInstance]:
        stmt = (
            select(ChallengeInstance)
            .where(
                ChallengeInstance.challenge_id == challenge_id,
                ChallengeInstance.user_id.is_(None),
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

    async def ensure_static_instance(
        self,
        db: AsyncSession,
        *,
        challenge: Challenge,
    ) -> ChallengeInstance:
        existing = await self.get_shared_instance(db, challenge_id=challenge.id)
        if existing:
            return existing

        instance = ChallengeInstance(challenge_id=challenge.id, user_id=None)
        instance.mark_starting()
        db.add(instance)
        await db.flush()
        await db.refresh(instance)

        try:
            launch = await self._launch_container(
                challenge=challenge,
                instance=instance,
                user=_SYSTEM_USER,
            )
        except Exception as exc:  # pragma: no cover - depends on runner availability
            message = str(exc)
            instance.mark_error(message)
            db.add(instance)
            await db.commit()
            await db.refresh(instance)
            raise InstanceLaunchError(message) from exc

        instance.mark_running(
            container_id=launch.container_id,
            connection_info=launch.connection_info,
            started_at=datetime.utcnow(),
            expires_at=None,
        )
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
        return instance

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

    async def check_runner_health(self) -> dict[str, Any]:
        if self._runner_mode == "kubernetes":
            return {
                "status": "unavailable",
                "runner": self._runner_mode,
                "detail": "Kubernetes runner requires external orchestrator integration",
            }

        if docker is None:
            return {
                "status": "error",
                "runner": self._runner_mode,
                "detail": "docker SDK not installed",
            }

        try:
            client = await asyncio.to_thread(self._create_docker_client)
        except Exception as exc:  # pragma: no cover - configuration errors
            return {"status": "error", "runner": self._runner_mode, "detail": str(exc)}

        try:
            await asyncio.to_thread(client.ping)
        except Exception as exc:  # pragma: no cover - ping failures
            detail = str(exc)
            status = "error"
        else:
            status = "ok"
            detail = "runner reachable"
        finally:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                pass

        return {"status": status, "runner": self._runner_mode, "detail": detail}

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
            # urllib.parse.urlunparse expects (scheme, netloc, path, params, query, fragment).
            # Passing only five components raises ValueError and prevents returning the
            # container access URL. Provide the full tuple even when params/query/fragment
            # are empty so dynamic instance launches succeed.
            return urlunparse((scheme, netloc, "/", "", "", ""))

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
        if self._runner_mode == "kubernetes":
            return await self._launch_kubernetes(challenge=challenge, instance=instance, user=user)

        return await self._launch_with_docker(challenge=challenge, instance=instance, user=user)

    async def _launch_with_docker(
        self,
        *,
        challenge: Challenge,
        instance: ChallengeInstance,
        user: User,
    ) -> LaunchResult:
        client = await asyncio.to_thread(self._create_docker_client)
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
                container_port = self._coerce_port(
                    getattr(challenge, "service_port", None)
                    or getattr(challenge, "service_internal_port", None)
                    or getattr(challenge, "internal_port", None)
                )
                if container_port is None:
                    container_port = await self._discover_image_port(client, challenge.docker_image)
                if container_port is None:
                    container_port = "80"
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

    def _create_docker_client(self):
        if docker is None:
            raise RuntimeError("Docker SDK is not available. Install the 'docker' package to continue.")

        if self._runner_mode == "remote-docker":
            base_url = os.getenv("REMOTE_DOCKER_HOST")
            if not base_url:
                raise RuntimeError("REMOTE_DOCKER_HOST must be set when CHALLENGE_RUNNER=remote-docker")

            verify_tls = os.getenv("REMOTE_DOCKER_TLS_VERIFY", "1").lower() in {
                "1",
                "true",
                "yes",
            }
            tls = None
            if verify_tls:
                if TLSConfig is None:
                    raise RuntimeError("docker TLS support is unavailable in this environment")
                ca_cert = os.getenv("REMOTE_DOCKER_CA_CERT")
                client_cert = os.getenv("REMOTE_DOCKER_CLIENT_CERT")
                client_key = os.getenv("REMOTE_DOCKER_CLIENT_KEY")
                cert_tuple = (client_cert, client_key) if client_cert and client_key else None
                tls = TLSConfig(ca_cert=ca_cert, client_cert=cert_tuple, verify=True)
            return docker.DockerClient(base_url=base_url, tls=tls)

        return docker.from_env()

    async def _launch_kubernetes(
        self,
        *,
        challenge: Challenge,
        instance: ChallengeInstance,
        user: User,
    ) -> LaunchResult:
        raise RuntimeError(
            "Kubernetes runner is not yet implemented in this deployment. "
            "Configure CHALLENGE_RUNNER to 'local' or 'remote-docker'."
        )

    async def _discover_image_port(self, client, image_name: Optional[str]) -> Optional[str]:
        """Try to infer the exposed container port from the image metadata."""

        if not image_name:
            return None

        async def _load_image():
            try:
                return await asyncio.to_thread(client.images.get, image_name)
            except DockerException:
                try:
                    return await asyncio.to_thread(client.images.pull, image_name)
                except DockerException:
                    return None

        image = await _load_image()
        if not image:
            return None

        config = getattr(image, "attrs", {}).get("Config", {})
        exposed = config.get("ExposedPorts") or {}
        for key in exposed.keys():
            port = self._coerce_port(key)
            if port:
                return port
        return None

    def _coerce_port(self, value: Optional[Any]) -> Optional[str]:
        """Normalize port hints (ints, strings like "8000/tcp", etc.) to a str."""

        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return str(int(value))
            except (ValueError, TypeError):
                return None
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            if "/" in candidate:
                candidate = candidate.split("/", 1)[0]
            return candidate if candidate.isdigit() else None
        return None

    async def _stop_container(self, container_id: Optional[str]) -> None:
        if not container_id:
            return
        if self._runner_mode == "kubernetes":
            _LOGGER.warning("Kubernetes runner does not support stop via API yet")
            return
        if docker is None:
            return
        client = await asyncio.to_thread(self._create_docker_client)
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
    def _ensure_launchable(
        self,
        challenge: Challenge,
        *,
        require_docker_image: bool = True,
    ) -> None:
        if not challenge.is_active or getattr(challenge, "is_private", False):
            raise InstanceNotAllowed("Challenge is not active")
        if require_docker_image and not challenge.docker_image:
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


async def runner_health() -> dict[str, Any]:
    service = get_container_service()
    return await service.check_runner_health()
