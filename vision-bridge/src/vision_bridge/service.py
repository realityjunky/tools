from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from mcp.server.mcpserver import Context
from PIL import Image

from vision_bridge.config import Settings
from vision_bridge.deadline import RequestDeadline, deadline_from_context
from vision_bridge.paths import validate_image_path

logger = logging.getLogger(__name__)

VISUAL_ANALYSIS_PROMPT = (
    "Describe the visible non-textual content of this image: objects, scene, layout, "
    "colours, and relationships. Do not transcribe, translate, or extract text. "
    "OCR and document parsing are outside this tool."
)


class ImageGateway(Protocol):
    def analyze_image(
        self,
        *,
        model: str,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        deadline: RequestDeadline,
    ) -> Awaitable[str]: ...


class VisionBridge:
    def __init__(self, settings: Settings, *, gateway: ImageGateway) -> None:
        self.settings = settings
        self.gateway = gateway

    async def vision_analyze_image(
        self,
        image_path: str,
        ctx: Context | None = None,
    ) -> str:
        """Analyze the non-textual visual content of a local image with Qwen3-VL-Plus.

        This tool intentionally does not perform OCR, text extraction, or document
        parsing. Configure a separate OCR MCP server when the task is to read
        text or table cells. Image bytes are held in memory only.
        """

        deadline = deadline_from_context(
            ctx,
            fallback_timeout_seconds=self.settings.request_timeout_seconds,
        )
        deadline.remaining_seconds()
        validated = validate_image_path(
            image_path,
            allowed_directories=self.settings.allowed_directories,
        )
        image_bytes = validated.path.read_bytes()
        result = await self.gateway.analyze_image(
            model=self.settings.vision_model,
            image_bytes=image_bytes,
            mime_type=_mime_type(validated.extension),
            prompt=VISUAL_ANALYSIS_PROMPT,
            deadline=deadline,
        )
        path_digest = hashlib.sha256(str(validated.path).encode()).hexdigest()[:16]
        content_digest = hashlib.sha256(image_bytes).hexdigest()[:16]
        logger.info(
            "vision_image_processed request_id=%s model=%s path_sha256=%s "
            "content_sha256=%s dimensions=%s",
            deadline.request_id or "none",
            self.settings.vision_model,
            path_digest,
            content_digest,
            _image_dimensions(image_bytes),
        )
        concern = (
            "Caution: this path appears sensitive and was processed only because it did "
            "not match a known-secret pattern.\n\n"
            if validated.sensitivity_concern
            else ""
        )
        safe_result = _redact_secrets(result, self.settings)
        return f"Model: {self.settings.vision_model}\n\n{concern}{safe_result}"


def _mime_type(extension: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }[extension]


def _redact_secrets(value: str, settings: Settings) -> str:
    return value.replace(settings.api_key, "[redacted]")


def _image_dimensions(image_bytes: bytes) -> str:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except Exception:  # pragma: no cover - format-specific decoder failures
        return "unknown"
    return f"{width}x{height}"
