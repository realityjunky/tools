from __future__ import annotations

import pytest

from vision_bridge.config import Settings
from vision_bridge.server import create_server


class NoCallGateway:
    async def analyze_image(self, **_: object) -> str:
        raise AssertionError("tool registration must not call the gateway")


@pytest.mark.asyncio
async def test_server_registers_the_single_vl_plus_visual_tool() -> None:
    server = create_server(
        Settings(
            gateway_url="https://gateway.example.test",
            api_key="sk-test-only",
        ),
        gateway=NoCallGateway(),
    )

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == ["vision_analyze_image"]
    tool = tools[0]
    assert tool.input_schema["required"] == ["image_path"]
    assert set(tool.input_schema["properties"]) == {"image_path"}
    assert "Qwen3-VL-Plus" in tool.description
    assert "OCR" in tool.description
    assert "separate OCR MCP" in tool.description
