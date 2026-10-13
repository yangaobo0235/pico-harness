"""Tests for pico.security.redaction: secret detection and artifact scrubbing."""

from pico.security.redaction import (
    REDACTED_VALUE,
    detected_secret_env_items,
    looks_sensitive_env_name,
    redact_artifact,
)


def test_sensitive_env_name_detection_matches_runtime_policy() -> None:
    """Name-based secrecy detection matches the markers the runtime uses and spares ordinary paths."""
    assert looks_sensitive_env_name("OPENAI_API_KEY")
    assert looks_sensitive_env_name("SERVICE_TOKEN")
    assert looks_sensitive_env_name("PASSWORD")
    assert not looks_sensitive_env_name("PATH")


def test_detected_secret_env_items_include_configured_and_sensitive_names() -> None:
    """Explicitly configured names and marker-matching names both surface, in sorted order."""
    env = {
        "PATH": "/bin",
        "CUSTOM_SECRET_NAME": "custom-value",
        "OPENAI_API_KEY": "api-value",
    }

    items = detected_secret_env_items(env=env, secret_env_names={"CUSTOM_SECRET_NAME"})

    assert items == [("CUSTOM_SECRET_NAME", "custom-value"), ("OPENAI_API_KEY", "api-value")]


def test_redact_artifact_recurses_through_values_and_secret_keys() -> None:
    """Scrubbing replaces secret-named fields outright and rewrites secret values at any depth."""
    artifact = {
        "OPENAI_API_KEY": "api-value",
        "payload": ["api-value", {"nested": "custom-value"}],
    }

    redacted = redact_artifact(
        artifact,
        env={"OPENAI_API_KEY": "api-value", "CUSTOM_SECRET_NAME": "custom-value"},
        secret_env_names={"CUSTOM_SECRET_NAME"},
    )

    assert redacted["OPENAI_API_KEY"] == REDACTED_VALUE
    assert redacted["payload"] == [REDACTED_VALUE, {"nested": REDACTED_VALUE}]
