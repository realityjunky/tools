from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from vision_bridge.config import DEFAULT_VISION_MODEL, Settings
from vision_bridge.deadline import RequestDeadline
from vision_bridge.service import VISUAL_ANALYSIS_PROMPT, VisionBridge


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze_image(self, **request: Any) -> str:
        self.calls.append(request)
        return "A small cat on a windowsill."


def _settings() -> Settings:
    return Settings(
        gateway_url="https://gateway.example.test",
        api_key="sk-test-only",
    )


@pytest.mark.asyncio
async def test_visual_tool_uses_only_the_fixed_vl_plus_model(tmp_path: Path) -> None:
    image_path = tmp_path / "cat.png"
    image_path.write_bytes(b"image bytes")
    gateway = RecordingGateway()
    bridge = VisionBridge(_settings(), gateway=gateway)

    result = await bridge.vision_analyze_image(str(image_path))

    assert gateway.calls[0]["model"] == DEFAULT_VISION_MODEL
    assert gateway.calls[0]["prompt"] == VISUAL_ANALYSIS_PROMPT
    assert "Model: qwen3-vl-plus" in result
    assert "cat" in result


@pytest.mark.asyncio
async def test_visual_tool_logs_only_safe_correlatable_telemetry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    image_path = tmp_path / "diagram.png"
    with Image.new("RGB", (2, 3), color="white") as image:
        image.save(image_path)
    bridge = VisionBridge(_settings(), gateway=RecordingGateway())

    with caplog.at_level(logging.INFO, logger="vision_bridge.service"):
        await bridge.vision_analyze_image(str(image_path))

    expected_path_digest = hashlib.sha256(str(image_path.resolve()).encode()).hexdigest()[:16]
    assert f"path_sha256={expected_path_digest}" in caplog.text
    assert "content_sha256=" in caplog.text
    assert "dimensions=2x3" in caplog.text
    assert str(image_path) not in caplog.text
    assert "sk-test-only" not in caplog.text


@pytest.mark.asyncio
async def test_successful_call_does_not_write_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"image bytes")
    bridge = VisionBridge(_settings(), gateway=RecordingGateway())

    def fail_if_written(_: Path, __: bytes) -> None:
        pytest.fail("successful image calls must not write files")

    monkeypatch.setattr(Path, "write_bytes", fail_if_written)
    await bridge.vision_analyze_image(str(image_path))


def test_deadline_object_rejects_expired_calls() -> None:
    deadline = RequestDeadline(expires_at_epoch_seconds=0)

    with pytest.raises(Exception, match="deadline exceeded"):
        deadline.remaining_seconds()
