from urllib.parse import parse_qs, urlsplit

import pytest

from app.database import _normalize_database_url, _database_url_from_env, _railway_env_database_url


def _query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def test_normalize_none_returns_none():
    assert _normalize_database_url(None) is None


def test_sqlite_url_remains_unchanged():
    url = "sqlite+aiosqlite:///tmp/test.db"
    assert _normalize_database_url(url) == url


@pytest.mark.parametrize(
    "raw, expected_prefix",
    [
        ("postgres://user:pass@db.example.com/app", "postgresql+asyncpg://"),
        (
            "postgresql://user:pass@db.example.com/app?sslmode=require",
            "postgresql+asyncpg://",
        ),
        ("postgresql+psycopg2://user@localhost/app", "postgresql+asyncpg://"),
    ],
)
def test_postgres_urls_use_asyncpg(raw: str, expected_prefix: str):
    normalized = _normalize_database_url(raw)
    assert normalized.startswith(expected_prefix)


def test_sslmode_require_becomes_asyncpg_ssl_true():
    normalized = _normalize_database_url(
        "postgres://user@localhost/app?sslmode=require&application_name=ctf"
    )
    params = _query_params(normalized)
    assert "sslmode" not in params
    assert params["ssl"] == ["true"]
    assert params["application_name"] == ["ctf"]


def test_sslmode_disable_becomes_asyncpg_ssl_false():
    normalized = _normalize_database_url("postgres://user@localhost/app?sslmode=disable")
    params = _query_params(normalized)
    assert params["ssl"] == ["false"]


def test_unhandled_sslmode_is_removed():
    normalized = _normalize_database_url("postgres://user@localhost/app?sslmode=prefer")
    params = _query_params(normalized)
    assert "ssl" not in params
    assert "sslmode" not in params


def test_database_url_prefers_database_url_env():
    env = {
        "DATABASE_URL": "postgresql://user:pass@db.example.com/app",
        "PGHOST": "ignored",
    }
    resolved = _database_url_from_env(env)
    assert resolved == _normalize_database_url(env["DATABASE_URL"])


def test_database_url_applies_pgsslmode_when_missing_ssl_flag():
    env = {
        "DATABASE_URL": "postgresql://user:pass@db.example.com/app",
        "PGSSLMODE": "require",
    }
    resolved = _database_url_from_env(env)
    params = _query_params(resolved)
    assert params["ssl"] == ["true"]


def test_pgsslmode_does_not_override_existing_ssl_flag():
    env = {
        "DATABASE_URL": "postgresql://user:pass@db.example.com/app?sslmode=disable",
        "PGSSLMODE": "require",
    }
    resolved = _database_url_from_env(env)
    params = _query_params(resolved)
    assert params["ssl"] == ["false"]


def test_database_url_uses_railway_pg_vars():
    env = {
        "PGHOST": "railway.internal",
        "PGDATABASE": "railway",
        "PGUSER": "postgres",
        "PGPASSWORD": "secret",
        "PGPORT": "6543",
    }
    resolved = _database_url_from_env(env)
    url = urlsplit(resolved)
    assert f"{url.scheme}://{url.hostname}:{url.port}{url.path}" == "postgresql+asyncpg://railway.internal:6543/railway"
    assert parse_qs(url.query) == {}
    assert url.username == "postgres"


def test_railway_env_adds_ssl_flag():
    env = {
        "PGHOST": "railway",
        "PGDATABASE": "railway",
        "PGUSER": "postgres",
        "PGSSLMODE": "require",
    }
    resolved = _railway_env_database_url(env)
    params = _query_params(resolved)
    assert params["ssl"] == ["true"]


def test_railway_env_missing_bits_returns_none():
    env = {"PGHOST": "railway"}
    assert _railway_env_database_url(env) is None
