from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import jsonschema
import pytest

from vision_bridge.config import Settings
from vision_bridge.server import create_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "contract" / "manifest.json"
SCHEMA_PATH = PROJECT_ROOT / "contract" / "manifest.schema.json"
GENERATOR_PATH = PROJECT_ROOT / "scripts" / "generate_mcp_contract.py"


class NoCallGateway:
    async def analyze_image(self, **_: object) -> str:
        raise AssertionError("contract inspection must not call the gateway")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_static_manifest_matches_the_single_runtime_tool() -> None:
    manifest = _read_json(MANIFEST_PATH)
    server = create_server(
        Settings(
            gateway_url="https://contract.invalid",
            api_key="contract-test-only",
        ),
        gateway=NoCallGateway(),
    )
    runtime_tools = [
        tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in await server.list_tools()
    ]

    assert manifest["generated_from"] == "server.list_tools"
    assert manifest["server"] == {
        "name": server.name,
        "description": server.description,
        "transport": "stdio",
    }
    assert manifest["tools"] == runtime_tools
    assert [tool["name"] for tool in runtime_tools] == ["vision_analyze_image"]


def test_manifest_validates_against_meta_schema() -> None:
    jsonschema.Draft202012Validator(_read_json(SCHEMA_PATH)).validate(_read_json(MANIFEST_PATH))


def test_contract_version_matches_python_project() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file_handle:
        version = tomllib.load(file_handle)["project"]["version"]
    assert _read_json(MANIFEST_PATH)["contract_version"] == version


def test_contract_generation_is_deterministic_and_check_mode_detects_stale_output(
    tmp_path: Path,
) -> None:
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]
    for output in outputs:
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--output", str(output)],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert outputs[0].read_bytes() == outputs[1].read_bytes()

    stale_manifest = tmp_path / "manifest.json"
    stale_manifest.write_text("{}\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check", "--output", str(stale_manifest)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "stale" in result.stderr.lower()
