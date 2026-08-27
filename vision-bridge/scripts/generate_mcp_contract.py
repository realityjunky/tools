from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from vision_bridge.config import Settings
from vision_bridge.server import create_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "contract" / "manifest.json"
SCHEMA_PATH = PROJECT_ROOT / "contract" / "manifest.schema.json"


class _NoCallGateway:
    async def analyze_image(self, **_: object) -> str:
        raise AssertionError("contract generation must not call the vision gateway")


def _project_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file_handle:
        return str(tomllib.load(file_handle)["project"]["version"])


async def build_manifest() -> dict[str, Any]:
    server = create_server(
        Settings(
            gateway_url="https://contract.invalid",
            api_key="contract-generation-only",
        ),
        gateway=_NoCallGateway(),
    )
    tools = await server.list_tools()
    manifest: dict[str, Any] = {
        "$schema": "./manifest.schema.json",
        "contract_version": _project_version(),
        "advertisement": "static",
        "generated_from": "server.list_tools",
        "server": {
            "name": server.name,
            "description": server.description,
            "transport": "stdio",
        },
        "tools": [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools
        ],
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)
    return manifest


def render_manifest(manifest: dict[str, Any]) -> str:
    return f"{json.dumps(manifest, ensure_ascii=False, indent=2)}\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate static Vision Bridge MCP tools/list contract."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = Path(args.output).resolve()
    rendered = render_manifest(asyncio.run(build_manifest()))
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print("Vision Bridge MCP manifest is stale.", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
