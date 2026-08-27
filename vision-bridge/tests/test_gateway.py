from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from vision_bridge.config import Settings
from vision_bridge.deadline import RequestDeadline
from vision_bridge.errors import BudgetExhausted, GatewayUnreachable, ModelError, RequestDeadlineExceeded
from vision_bridge.gateway import OpenAICompatibleGateway
from vision_bridge.service import VISUAL_ANALYSIS_PROMPT, VisionBridge


def _settings() -> Settings:
    return Settings(
        gateway_url="https://gateway.example.test",
        api_key="sk-secret-must-not-escape",
    )


@pytest.mark.asyncio
async def test_gateway_posts_fixed_model_image_and_shared_deadline(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A cat."}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    image_path = tmp_path / "cat.png"
    image_path.write_bytes(b"image bytes")
    bridge = VisionBridge(_settings(), gateway=OpenAICompatibleGateway(_settings(), http_client=client))

    result = await bridge.vision_analyze_image(str(image_path))

    await client.aclose()
    payload = json.loads(requests[0].content)
    assert payload["model"] == "qwen3-vl-plus"
    assert payload["messages"][0]["content"][0]["text"] == VISUAL_ANALYSIS_PROMPT
    assert payload["messages"][0]["content"][1]["type"] == "image_url"
    assert "A cat." in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(402, BudgetExhausted), (500, ModelError)],
)
async def test_gateway_classifies_safe_http_failures(
    tmp_path: Path,
    status_code: int,
    error_type: type[Exception],
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code, text="failure"))
    )
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"image bytes")
    bridge = VisionBridge(_settings(), gateway=OpenAICompatibleGateway(_settings(), http_client=client))

    with pytest.raises(error_type):
        await bridge.vision_analyze_image(str(image_path))

    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_maps_transport_timeout_to_the_shared_deadline() -> None:
    class TimeoutClient:
        async def post(self, *_: object, **__: object) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://gateway.example.test"))

    gateway = OpenAICompatibleGateway(_settings(), http_client=TimeoutClient())  # type: ignore[arg-type]

    with pytest.raises(RequestDeadlineExceeded):
        await gateway.analyze_image(
            model="qwen3-vl-plus",
            image_bytes=b"image bytes",
            mime_type="image/png",
            prompt=VISUAL_ANALYSIS_PROMPT,
            deadline=RequestDeadline(time.time() + 5),
        )


@pytest.mark.asyncio
async def test_gateway_maps_network_failures_without_logging_the_key() -> None:
    class NetworkClient:
        async def post(self, *_: object, **__: object) -> httpx.Response:
            raise httpx.ConnectError("offline", request=httpx.Request("POST", "https://gateway.example.test"))

    gateway = OpenAICompatibleGateway(_settings(), http_client=NetworkClient())  # type: ignore[arg-type]

    with pytest.raises(GatewayUnreachable):
        await gateway.analyze_image(
            model="qwen3-vl-plus",
            image_bytes=b"image bytes",
            mime_type="image/png",
            prompt=VISUAL_ANALYSIS_PROMPT,
            deadline=RequestDeadline(time.time() + 5),
        )
