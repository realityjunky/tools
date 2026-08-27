import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  buildPrepareUvArgs,
  buildUvArgs,
  findUvCommand,
  isPrepareCommand,
} from "../bin/vision-bridge.mjs";
import {
  VisionBridgeBackend,
  VisionBridgeStartupError,
  requestTimeoutMs,
  startupTimeoutMs,
} from "../src/npm-server.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const launcher = resolve(root, "bin/vision-bridge.mjs");

test("package metadata and static contract advertise the VL-only release", async () => {
  const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  const pyproject = await readFile(resolve(root, "pyproject.toml"), "utf8");
  const manifest = JSON.parse(await readFile(resolve(root, "contract/manifest.json"), "utf8"));

  assert.equal(packageJson.name, "@hugobiotech/vision-bridge");
  assert.equal(packageJson.version, "0.2.1");
  assert.match(pyproject, /version = "0\.2\.1"/);
  assert.deepEqual(manifest.tools.map((tool) => tool.name), ["vision_analyze_image"]);
  assert.match(manifest.server.description, /Qwen3-VL-Plus/);
  assert.doesNotMatch(JSON.stringify(manifest), /Qwen3\.5-VL-Plus/);
  assert.doesNotMatch(JSON.stringify(manifest), /vision_read_document|extract_text/);
});

test("launcher separates explicit preparation from offline locked MCP startup", () => {
  assert.deepEqual(buildPrepareUvArgs("/package"), [
    "sync",
    "--quiet",
    "--locked",
    "--no-default-groups",
    "--project",
    "/package",
  ]);
  assert.deepEqual(buildUvArgs("/package"), [
    "run",
    "--quiet",
    "--offline",
    "--locked",
    "--no-sync",
    "--no-default-groups",
    "--project",
    "/package",
    "vision-bridge",
  ]);
  assert.equal(isPrepareCommand(["--prepare"]), true);
  assert.equal(isPrepareCommand([]), false);
  assert.equal(isPrepareCommand(["--prepare", "unexpected"]), false);
});

test("launcher discovers uv from a desktop user's local bin outside PATH", () => {
  const expected = "/home/desktop-user/.local/bin/uv";
  assert.equal(
    findUvCommand(
      { HOME: "/home/desktop-user" },
      { platform: "linux", canExecute: (candidate) => candidate === expected },
    ),
    expected,
  );
});

test("single request deadline is forwarded as safe MCP metadata", async () => {
  const calls = [];
  const telemetry = [];
  const backend = new VisionBridgeBackend({
    command: "unused",
    args: [],
    cwd: root,
    environment: {},
    requestTimeoutMs: 500,
    telemetry: (event, fields) => telemetry.push({ event, fields }),
  });
  backend.ready = Promise.resolve({
    callTool: async (...arguments_) => {
      calls.push(arguments_);
      return { content: [{ type: "text", text: "ok" }] };
    },
  });

  const result = await backend.callTool({
    name: "vision_analyze_image",
    arguments: { image_path: "/tmp/cat.png" },
    _meta: { progressToken: "safe-token" },
  });

  assert.equal(result.content[0].text, "ok");
  assert.ok(calls[0][2].timeout > 1_000);
  assert.ok(calls[0][2].timeout <= 1_500);
  assert.equal(calls[0][0]._meta.progressToken, "safe-token");
  const metadata = calls[0][0]._meta["io.hugobiotech/vision-bridge"];
  assert.equal(typeof metadata.request_id, "string");
  assert.equal(typeof metadata.deadline_unix_ms, "number");
  assert.ok(metadata.deadline_unix_ms > Date.now());
  assert.deepEqual(
    telemetry.map(({ event }) => event),
    ["request_start", "request_complete"],
  );
  assert.equal(JSON.stringify(telemetry).includes("/tmp/cat.png"), false);
});

test("startup uses a bounded deterministic readiness check", async () => {
  const backend = new VisionBridgeBackend({
    command: "unused",
    args: [],
    cwd: root,
    environment: {},
    startupTimeoutMs: 5,
    telemetry: () => {},
  });
  backend.ready = new Promise(() => {});

  await assert.rejects(
    backend.waitUntilReady(),
    (error) => error instanceof VisionBridgeStartupError && /within 5ms/.test(error.message),
  );
});

test("timeout parsing exposes one user-facing request deadline", () => {
  assert.equal(requestTimeoutMs({}), 120_000);
  assert.equal(requestTimeoutMs({ VISION_BRIDGE_REQUEST_TIMEOUT_MS: "175000" }), 175_000);
  assert.equal(requestTimeoutMs({ VISION_BRIDGE_REQUEST_TIMEOUT_MS: "invalid" }), 120_000);
  assert.equal(startupTimeoutMs({}), 20_000);
});

test("launcher forwards a request only after its Python backend is ready", async () => {
  const directory = await mkdtemp(resolve(tmpdir(), "vision-bridge-fake-uv-"));
  const fakeUv = resolve(directory, "uv.mjs");
  await writeFile(
    fakeUv,
    `#!/usr/bin/env node
import readline from "node:readline";
const lines = readline.createInterface({ input: process.stdin });
lines.on("line", (line) => {
  const request = JSON.parse(line);
  if (request.method === "initialize") {
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: request.id,
      result: {
        protocolVersion: request.params.protocolVersion,
        capabilities: { tools: {} },
        serverInfo: { name: "fake-python-backend", version: "1.0.0" },
      },
    }) + "\\n");
  }
  if (request.method === "tools/call") {
    const metadata = request.params._meta["io.hugobiotech/vision-bridge"];
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: request.id,
      result: { content: [{ type: "text", text: JSON.stringify(metadata) }] },
    }) + "\\n");
  }
});
`,
    "utf8",
  );
  await chmod(fakeUv, 0o755);
  const child = spawn(process.execPath, [launcher], {
    env: {
      ...process.env,
      VISION_BRIDGE_UV_COMMAND: fakeUv,
      VISION_BRIDGE_REQUEST_TIMEOUT_MS: "5000",
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  try {
    const initialized = await initialize(child);
    assert.equal(initialized.result.serverInfo.name, "vision-bridge");

    child.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n`,
    );
    const list = await readJsonLine(child.stdout, 1_000);
    assert.deepEqual(list.result.tools.map((tool) => tool.name), ["vision_analyze_image"]);

    child.stdin.write(
      `${JSON.stringify({
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: {
          name: "vision_analyze_image",
          arguments: { image_path: "/tmp/cat.png" },
        },
      })}\n`,
    );
    const response = await readJsonLine(child.stdout, 1_000);
    const metadata = JSON.parse(response.result.content[0].text);
    assert.equal(typeof metadata.request_id, "string");
    assert.equal(typeof metadata.deadline_unix_ms, "number");
  } finally {
    child.kill("SIGTERM");
  }
});

test("launcher advertises its static contract while Python starts", async () => {
  const temporaryDirectory = await mkdtemp(resolve(tmpdir(), "vision-bridge-slow-uv-"));
  const fakeUv = resolve(temporaryDirectory, "uv.mjs");
  await writeFile(
    fakeUv,
    `#!/usr/bin/env node
import readline from "node:readline";
const lines = readline.createInterface({ input: process.stdin });
lines.on("line", () => {});
`,
  );
  await chmod(fakeUv, 0o755);
  const child = spawn(process.execPath, [launcher], {
    env: {
      ...process.env,
      VISION_BRIDGE_UV_COMMAND: fakeUv,
      VISION_BRIDGE_STARTUP_TIMEOUT_MS: "10000",
    },
    stdio: ["pipe", "pipe", "pipe"],
  });

  try {
    const initialized = await initialize(child);
    assert.equal(initialized.result.serverInfo.name, "vision-bridge");
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" })}\n`);
    const list = await readJsonLine(child.stdout, 1_000);
    assert.deepEqual(list.result.tools.map((tool) => tool.name), ["vision_analyze_image"]);
  } finally {
    child.kill("SIGTERM");
  }
});

async function initialize(child) {
  child.stdin.write(
    `${JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "vision-bridge-test", version: "1.0.0" },
      },
    })}\n`,
  );
  const response = await readJsonLine(child.stdout, 1_000);
  child.stdin.write(
    `${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`,
  );
  return response;
}

function readJsonLine(stream, timeoutMs) {
  return new Promise((resolveLine, reject) => {
    let buffer = "";
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("timed out waiting for JSON-RPC response"));
    }, timeoutMs);
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const newline = buffer.indexOf("\n");
      if (newline === -1) {
        return;
      }
      const line = buffer.slice(0, newline);
      cleanup();
      resolveLine(JSON.parse(line));
    };
    const cleanup = () => {
      clearTimeout(timer);
      stream.off("data", onData);
    };
    stream.on("data", onData);
  });
}
