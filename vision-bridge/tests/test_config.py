from __future__ import annotations

import pytest

from vision_bridge.config import (
    CONFIG_REVISION,
    DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_VISION_MODEL,
    Settings,
)
from vision_bridge.errors import ConfigurationError


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "VISION_BRIDGE_GATEWAY_URL": "https://gateway.example.test",
        "VISION_BRIDGE_API_KEY": "sk-test-only",
        "VISION_BRIDGE_CONFIG_REVISION": CONFIG_REVISION,
    }
    values.update(overrides)
    return values


def test_uses_fixed_qwen35_vl_plus_model_and_one_default_deadline() -> None:
    settings = Settings.from_env(_environment())

    assert settings.vision_model == DEFAULT_VISION_MODEL
    assert settings.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_MS / 1_000
    assert "sk-test-only" not in repr(settings)


def test_stale_configuration_is_a_clear_startup_error_without_key_disclosure() -> None:
    secret_key = "sk-vision-must-never-leak"

    with pytest.raises(ConfigurationError) as caught:
        Settings.from_env(
            {
                "VISION_BRIDGE_GATEWAY_URL": "https://gateway.example.test",
                "VISION_BRIDGE_API_KEY": secret_key,
            }
        )

    assert caught.value.identity == "configuration_error"
    assert "stale" in str(caught.value).lower()
    assert secret_key not in str(caught.value)


def test_request_timeout_can_be_overridden_once_for_every_hop() -> None:
    settings = Settings.from_env(_environment(VISION_BRIDGE_REQUEST_TIMEOUT_MS="180000"))

    assert settings.request_timeout_seconds == 180


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_request_timeout_must_be_a_positive_integer(value: str) -> None:
    with pytest.raises(ConfigurationError, match="VISION_BRIDGE_REQUEST_TIMEOUT_MS"):
        Settings.from_env(_environment(VISION_BRIDGE_REQUEST_TIMEOUT_MS=value))


def test_allowed_directories_are_parsed_without_legacy_model_or_ocr_settings() -> None:
    settings = Settings.from_env(
        _environment(VISION_BRIDGE_ALLOWED_DIRS='["/safe/images", "/safe/screenshots"]')
    )

    assert [str(path) for path in settings.allowed_directories] == [
        "/safe/images",
        "/safe/screenshots",
    ]
    assert not hasattr(settings, "ocr_model")
    assert not hasattr(settings, "mineru_api_key")
