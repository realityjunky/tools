from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vision_bridge.config import Settings
from vision_bridge.errors import (
    DirectoryNotAllowed,
    ExtensionNotAllowed,
    FileTooLarge,
    PathNotFound,
    SecretPatternRefused,
)
from vision_bridge.paths import MAX_IMAGE_BYTES
from vision_bridge.service import VisionBridge


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze_image(self, **request: Any) -> str:
        self.calls.append(request)
        return "gateway result"


def _bridge(**overrides: Any) -> VisionBridge:
    values = {
        "gateway_url": "https://gateway.example.test",
        "api_key": "sk-test-only",
    }
    values.update(overrides)
    return VisionBridge(Settings(**values), gateway=RecordingGateway())


@pytest.mark.asyncio
async def test_extension_is_rejected_before_existence_or_gateway_access(tmp_path: Path) -> None:
    bridge = _bridge()

    with pytest.raises(ExtensionNotAllowed) as caught:
        await bridge.vision_analyze_image(str(tmp_path / "does-not-exist.txt"))

    assert caught.value.identity == "extension_not_allowed"


@pytest.mark.asyncio
async def test_known_secret_name_is_refused_even_with_an_allowed_image_extension(tmp_path: Path) -> None:
    secret_path = tmp_path / "secret-key.png"
    secret_path.write_bytes(b"image")
    bridge = _bridge()

    with pytest.raises(SecretPatternRefused) as caught:
        await bridge.vision_analyze_image(str(secret_path))

    assert caught.value.identity == "secret_pattern_refused"


@pytest.mark.asyncio
async def test_env_name_without_allowed_suffix_is_rejected(tmp_path: Path) -> None:
    bridge = _bridge()

    with pytest.raises(ExtensionNotAllowed):
        await bridge.vision_analyze_image(str(tmp_path / ".env"))


@pytest.mark.asyncio
async def test_symlink_target_is_checked_against_secret_patterns(tmp_path: Path) -> None:
    secret_path = tmp_path / "credentials.png"
    secret_path.write_bytes(b"image")
    safe_link = tmp_path / "photo.png"
    safe_link.symlink_to(secret_path)
    bridge = _bridge()

    with pytest.raises(SecretPatternRefused):
        await bridge.vision_analyze_image(str(safe_link))


@pytest.mark.asyncio
async def test_size_cap_uses_stat_before_reading_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_path = tmp_path / "large.png"
    image_path.write_bytes(b"x")
    bridge = _bridge()

    class OversizedStat:
        st_size = MAX_IMAGE_BYTES + 1

    monkeypatch.setattr(Path, "stat", lambda _: OversizedStat())
    with pytest.raises(FileTooLarge) as caught:
        await bridge.vision_analyze_image(str(image_path))

    assert caught.value.identity == "file_too_large"


@pytest.mark.asyncio
async def test_missing_allowed_image_has_a_distinct_not_found_error(tmp_path: Path) -> None:
    bridge = _bridge()

    with pytest.raises(PathNotFound) as caught:
        await bridge.vision_analyze_image(str(tmp_path / "missing.png"))

    assert caught.value.identity == "not_found"


@pytest.mark.asyncio
async def test_optional_directory_allow_list_uses_resolved_path(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    image_path = outside / "image.png"
    image_path.write_bytes(b"image")
    bridge = _bridge(allowed_directories=(approved,))

    with pytest.raises(DirectoryNotAllowed) as caught:
        await bridge.vision_analyze_image(str(image_path))

    assert caught.value.identity == "directory_not_allowed"
