from datetime import datetime, timedelta, timezone

from app.models.challenge import Challenge, DeploymentType
from app.models.challenge_instance import ChallengeInstance
from app.routes.challenges import _challenge_to_public, _select_display_instance


def _make_challenge() -> Challenge:
    challenge = Challenge(
        id=1,
        title="Test",
        description="desc",
        category_id=1,
        points=100,
        difficulty="easy",
    )
    challenge.tags = []
    challenge.hints = []
    challenge.attachments = []
    challenge.created_at = datetime.now(timezone.utc)
    challenge.is_active = True
    challenge.is_private = False
    challenge.service_url_path = "/challenge1/"
    challenge.deployment_type = DeploymentType.dynamic_container
    challenge.always_on = False
    return challenge


def test_challenge_to_public_includes_active_instance():
    challenge = _make_challenge()
    instance = ChallengeInstance(
        id=5,
        challenge_id=challenge.id,
        user_id=2,
        status="running",
        container_id="abc123",
        connection_info={"host": "localhost", "ports": []},
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    result = _challenge_to_public(challenge, instance=instance)

    assert result.active_instance is not None
    assert result.active_instance.status == "running"
    assert result.active_instance.container_id == "abc123"
    assert result.active_instance.access_url == "/challenge1/"
    assert result.access_url == "/challenge1/"


def test_select_display_instance_filters_expired_and_stopped():
    active = ChallengeInstance(
        challenge_id=1,
        user_id=1,
        status="running",
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    selected = _select_display_instance(active)
    assert selected is not None
    assert selected.started_at.tzinfo is timezone.utc
    assert selected.expires_at.tzinfo is timezone.utc

    expired = ChallengeInstance(
        challenge_id=1,
        user_id=1,
        status="running",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert _select_display_instance(expired) is None

    stopped = ChallengeInstance(
        challenge_id=1,
        user_id=1,
        status="stopped",
    )
    assert _select_display_instance(stopped) is None
