from __future__ import annotations

import base64
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from vision_bridge.config import Settings
from vision_bridge.deadline import RequestDeadline
from vision_bridge.errors import (
    BudgetExhausted,
    GatewayUnreachable,
    ModelError,
    RequestDeadlineExceeded,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleGateway:
    """In-memory OpenAI-compatible gateway for the fixed visual model."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.http_client = http_client

    async def analyze_image(
        self,
        *,
        model: str,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        deadline: RequestDeadline,
    ) -> str:
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded_image}"
                            },
                        },
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        try:
            response = await self._post(
                self._completion_url(),
                headers=headers,
                payload=payload,
                timeout_seconds=deadline.remaining_seconds(),
            )
        except httpx.TimeoutException as exc:
            logger.info("vision_gateway_deadline_exceeded")
            raise RequestDeadlineExceeded("Vision Bridge request deadline exceeded") from exc
        except httpx.RequestError as exc:
            logger.warning("vision_gateway_unreachable")
            raise GatewayUnreachable("vision gateway is unreachable") from exc
        if response.status_code >= 400:
            if _is_budget_failure(response):
                raise BudgetExhausted("vision gateway budget exhausted")
            raise ModelError("vision model returned an error")
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ModelError("vision model returned an invalid response") from exc
        content = _extract_content(response_payload)
        if not content:
            raise ModelError("vision model returned no content")
        return content.replace(self.settings.api_key, "[redacted]")

    async def _post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> httpx.Response:
        if self.http_client is not None:
            return await self.http_client.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await client.post(url, headers=headers, json=payload)

    def _completion_url(self) -> str:
        suffix = "/chat/completions" if self.settings.gateway_url.endswith("/v1") else "/v1/chat/completions"
        return f"{self.settings.gateway_url}{suffix}"


def _is_budget_failure(response: httpx.Response) -> bool:
    if response.status_code in {402, 429}:
        return True
    return "budget" in response.text.casefold()


def _extract_content(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return None
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    text_parts = [
        part.get("text", "").strip()
        for part in content
        if isinstance(part, Mapping) and isinstance(part.get("text"), str)
    ]
    joined = "\n".join(part for part in text_parts if part)
    return joined or None
