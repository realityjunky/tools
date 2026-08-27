from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from vision_bridge.config import Settings
from vision_bridge.errors import ConfigurationError
from vision_bridge.gateway import OpenAICompatibleGateway
from vision_bridge.service import ImageGateway, VisionBridge


def create_server(
    settings: Settings | None = None,
    *,
    gateway: ImageGateway | None = None,
) -> MCPServer:
    resolved_settings = settings or Settings.from_env()
    resolved_gateway = gateway or OpenAICompatibleGateway(resolved_settings)
    bridge = VisionBridge(resolved_settings, gateway=resolved_gateway)
    server = MCPServer(
        name="vision-bridge",
        description=(
            "Local visual image analysis through Qwen3-VL-Plus. OCR, text extraction, "
            "and document parsing are intentionally excluded; configure a separate OCR MCP "
            "server for those tasks."
        ),
    )
    server.tool(name="vision_analyze_image")(bridge.vision_analyze_image)
    return server


def main() -> int:
    try:
        server = create_server()
    except ConfigurationError as exc:
        print(f"vision-bridge configuration error: {exc}", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


__all__ = ["create_server", "main"]
