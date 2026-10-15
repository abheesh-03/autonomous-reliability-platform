"""Tests for config.py -- bounds are clamped to a sane range, matching
the exact convention investigator_service.config/retrieval_service.config
already establish."""

import os

import psycopg
import pytest

from agent_runtime_service.config import CheckpointDbSettings, InvalidCheckpointIdentityError, RuntimeBounds


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AGENT_RUNTIME_"):
            monkeypatch.delenv(key, raising=False)


def test_runtime_bounds_defaults():
    bounds = RuntimeBounds.from_env()
    assert bounds.max_history_items == 50
    assert bounds.max_error_detail_chars == 300


def test_runtime_bounds_clamp_out_of_range_values(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_MAX_HISTORY_ITEMS", "999999")
    monkeypatch.setenv("AGENT_RUNTIME_MAX_ERROR_DETAIL_CHARS", "1")
    bounds = RuntimeBounds.from_env()
    assert bounds.max_history_items == 500  # clamped to the maximum
    assert bounds.max_error_detail_chars == 50  # clamped to the minimum


def test_checkpoint_db_settings_defaults_to_dedicated_role():
    settings = CheckpointDbSettings.from_env()
    assert settings.user == "agent_runtime"
    assert settings.schema == "agent_runtime"
    assert settings.host == "postgres"


def test_checkpoint_db_settings_conn_string_uses_configured_values(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_DB_HOST", "dbhost")
    monkeypatch.setenv("AGENT_RUNTIME_DB_PORT", "5555")
    monkeypatch.setenv("AGENT_RUNTIME_DB_USER", "agent_runtime")
    monkeypatch.setenv("AGENT_RUNTIME_DB_PASSWORD", "secret-value")
    monkeypatch.setenv("POSTGRES_DB", "mydb")
    settings = CheckpointDbSettings.from_env()
    conn = settings.conn_string()
    parsed = psycopg.conninfo.conninfo_to_dict(conn)
    assert parsed["user"] == "agent_runtime"
    assert parsed["password"] == "secret-value"
    assert parsed["host"] == "dbhost"
    assert parsed["port"] == "5555"
    assert parsed["dbname"] == "mydb"


def test_checkpoint_db_settings_conn_string_handles_reserved_uri_characters(monkeypatch):
    """Phase 7 correction round (finding #10): an operator-supplied
    password containing @, :, /, ?, # would silently break a naive
    f-string/URI-built connection string. Proves the real
    round-trip (build -> parse back) preserves the password exactly,
    using psycopg's own conninfo parser -- the same one
    AsyncPostgresSaver.from_conn_string ultimately uses."""
    reserved_password = "p@ss:word/with#chars?and spaces"
    monkeypatch.setenv("AGENT_RUNTIME_DB_USER", "agent_runtime")
    monkeypatch.setenv("AGENT_RUNTIME_DB_PASSWORD", reserved_password)
    monkeypatch.setenv("POSTGRES_DB", "mydb")
    settings = CheckpointDbSettings.from_env()
    conn = settings.conn_string()
    parsed = psycopg.conninfo.conninfo_to_dict(conn)
    assert parsed["password"] == reserved_password
    assert parsed["user"] == "agent_runtime"
    assert parsed["dbname"] == "mydb"


def test_checkpoint_db_settings_rejects_a_non_agent_runtime_user(monkeypatch):
    """Phase 7 correction round (finding #6): user/schema are an
    architectural security constant, not a normal operator tuning knob
    -- fail closed rather than silently connect as a broader role."""
    monkeypatch.setenv("AGENT_RUNTIME_DB_USER", "postgres")
    with pytest.raises(InvalidCheckpointIdentityError):
        CheckpointDbSettings.from_env()


def test_checkpoint_db_settings_rejects_a_non_agent_runtime_schema(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_DB_SCHEMA", "reliability")
    with pytest.raises(InvalidCheckpointIdentityError):
        CheckpointDbSettings.from_env()


def test_runtime_bounds_includes_incident_text_bound_with_investigator_service_defaults():
    """Mirrors investigator-service's own INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH
    default/range exactly -- same underlying V1 schema, same risk."""
    bounds = RuntimeBounds.from_env()
    assert bounds.max_incident_text_chars == 2000


def test_runtime_bounds_clamps_incident_text_bound(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_MAX_INCIDENT_TEXT_LENGTH", "50")
    bounds = RuntimeBounds.from_env()
    assert bounds.max_incident_text_chars == 100  # clamped to the minimum
