from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from vision_bridge.errors import ConfigurationError

# This is intentionally not configurable. Vision Bridge is a narrow visual
# analysis bridge; OCR and document parsing belong to a separate OCR MCP server.
DEFAULT_VISION_MODEL = "qwen3-vl-plus"
CONFIG_REVISION = "vl-plus-only-v2"
DEFAULT_REQUEST_TIMEOUT_MS = 120_000


@dataclass(frozen=True, slots=True)
class Settings:
    gateway_url: str
    api_key: str = field(repr=False)
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_MS / 1_000
    allowed_directories: tuple[Path, ...] = ()
    vision_model: str = field(default=DEFAULT_VISION_MODEL, init=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env
        gateway_url = values.get("VISION_BRIDGE_GATEWAY_URL", "").strip()
        if not gateway_url:
            raise ConfigurationError(
                "VISION_BRIDGE_GATEWAY_URL is required in the MCP server configuration"
            )

        api_key = values.get("VISION_BRIDGE_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "VISION_BRIDGE_API_KEY is required in the MCP server configuration"
            )

        revision = values.get("VISION_BRIDGE_CONFIG_REVISION", "").strip()
        if revision != CONFIG_REVISION:
            raise ConfigurationError(
                "Vision Bridge configuration is stale. Replace the complete Vision Bridge "
                "configuration from Model API Keys."
            )

        allowed_directories = _parse_allowed_directories(
            values.get("VISION_BRIDGE_ALLOWED_DIRS", "")
        )
        request_timeout_ms = _parse_positive_timeout_ms(
            values.get("VISION_BRIDGE_REQUEST_TIMEOUT_MS", "")
        )
        return cls(
            gateway_url=gateway_url.rstrip("/"),
            api_key=api_key,
            request_timeout_seconds=request_timeout_ms / 1_000,
            allowed_directories=allowed_directories,
        )


def _parse_positive_timeout_ms(raw: str) -> int:
    if not raw.strip():
        return DEFAULT_REQUEST_TIMEOUT_MS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            "VISION_BRIDGE_REQUEST_TIMEOUT_MS must be a positive integer"
        ) from exc
    if value <= 0:
        raise ConfigurationError(
            "VISION_BRIDGE_REQUEST_TIMEOUT_MS must be a positive integer"
        )
    return value


def _parse_allowed_directories(raw: str) -> tuple[Path, ...]:
    if not raw.strip():
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            "VISION_BRIDGE_ALLOWED_DIRS must be a JSON array of directory paths"
        ) from exc
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) and item.strip() for item in parsed
    ):
        raise ConfigurationError(
            "VISION_BRIDGE_ALLOWED_DIRS must be a JSON array of directory paths"
        )
    return tuple(Path(item).expanduser() for item in parsed)
