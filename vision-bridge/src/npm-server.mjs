import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const DEFAULT_STARTUP_TIMEOUT_MS = 20_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 120_000;
const OUTER_TIMEOUT_GRACE_MS = 1_000;
const DEADLINE_META_KEY = "io.hugobiotech/vision-bridge";

export class VisionBridgeStartupError extends Error {}
export class VisionBridgeRequestDeadlineError extends Error {}

export class VisionBridgeBackend {
  constructor({
    command,
    args,
    cwd,
    environment,
    startupTimeoutMs = DEFAULT_STARTUP_TIMEOUT_MS,
    requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
    telemetry = emitTelemetry,
  }) {
    this.command = command;
    this.args = args;
    this.cwd = cwd;
    this.environment = environment;
    this.startupTimeoutMs = startupTimeoutMs;
    this.requestTimeoutMs = requestTimeoutMs;
    this.telemetry = telemetry;
    this.client = undefined;
    this.transport = undefined;
    this.ready = undefined;
    this.startError = undefined;
  }

  start() {
    if (!this.ready) {
      const startedAt = Date.now();
      this.telemetry("backend_start", {});
      this.ready = this.connect()
        .then((client) => {
          this.telemetry("backend_ready", { duration_ms: Date.now() - startedAt });
          return client;
        })
        .catch((error) => {
          this.startError = error;
          this.telemetry("backend_failed", {
            duration_ms: Date.now() - startedAt,
            error_kind: errorKind(error),
          });
          throw error;
        });
    }
    return this.ready;
  }

  async connect() {
    this.client = new Client({
      name: "vision-bridge-node-proxy",
      version: "0.2.0",
    });
    this.transport = new StdioClientTransport({
      command: this.command,
      args: this.args,
      cwd: this.cwd,
      env: this.environment,
      stderr: "inherit",
    });
    await this.client.connect(this.transport);
    return this.client;
  }

  async callTool(params) {
    const requestId = randomUUID();
    const startedAt = Date.now();
    const deadlineUnixMs = startedAt + this.requestTimeoutMs;
    const tool = typeof params.name === "string" ? params.name : "unknown";
    this.telemetry("request_start", { request_id: requestId, tool });
    try {
      const remainingBeforeStartupMs = deadlineUnixMs - Date.now();
      if (remainingBeforeStartupMs <= 0) {
        throw new VisionBridgeRequestDeadlineError("Vision Bridge request deadline exceeded");
      }
      const client = await this.waitUntilReady({
        timeoutMs: Math.min(this.startupTimeoutMs, remainingBeforeStartupMs),
        timeoutIsRequestDeadline: remainingBeforeStartupMs <= this.startupTimeoutMs,
      });
      const remainingRequestMs = deadlineUnixMs - Date.now();
      if (remainingRequestMs <= 0) {
        throw new VisionBridgeRequestDeadlineError("Vision Bridge request deadline exceeded");
      }
      const result = await client.callTool(
        withRequestDeadline(params, { deadlineUnixMs, requestId }),
        undefined,
        { timeout: remainingRequestMs + OUTER_TIMEOUT_GRACE_MS },
      );
      this.telemetry(
        isDeadlineToolResult(result) ? "request_deadline_exceeded" : "request_complete",
        {
          request_id: requestId,
          tool,
          duration_ms: Date.now() - startedAt,
        },
      );
      return result;
    } catch (error) {
      const event =
        error instanceof VisionBridgeRequestDeadlineError || isTimeoutError(error)
          ? "request_deadline_exceeded"
          : "request_failed";
      this.telemetry(event, {
        request_id: requestId,
        tool,
        duration_ms: Date.now() - startedAt,
        error_kind: errorKind(error),
      });
      if (event === "request_deadline_exceeded") {
        throw new VisionBridgeRequestDeadlineError("Vision Bridge request deadline exceeded");
      }
      throw error;
    }
  }

  async waitUntilReady({
    timeoutMs = this.startupTimeoutMs,
    timeoutIsRequestDeadline = false,
  } = {}) {
    let client;
    try {
      client = await withTimeout(
        this.start(),
        timeoutMs,
        timeoutIsRequestDeadline ? undefined : () => this.close(),
      );
    } catch (error) {
      if (timeoutIsRequestDeadline && isTimeoutError(error)) {
        throw new VisionBridgeRequestDeadlineError("Vision Bridge request deadline exceeded");
      }
      throw startupError(error, timeoutMs);
    }
    if (!client) {
      throw startupError(
        this.startError || new Error("Python backend failed to start"),
        timeoutMs,
      );
    }
    return client;
  }

  async close() {
    const client = this.client;
    const transport = this.transport;
    this.client = undefined;
    this.transport = undefined;
    if (client) {
      await client.close();
      return;
    }
    await transport?.close();
  }
}

export function startupTimeoutMs(environment = process.env) {
  return positiveInteger(
    environment.VISION_BRIDGE_STARTUP_TIMEOUT_MS,
    DEFAULT_STARTUP_TIMEOUT_MS,
  );
}

export function requestTimeoutMs(environment = process.env) {
  return positiveInteger(
    environment.VISION_BRIDGE_REQUEST_TIMEOUT_MS,
    DEFAULT_REQUEST_TIMEOUT_MS,
  );
}

export function createVisionBridgeServer({ manifest, version, backend }) {
  const advertisedTools = new Set(manifest.tools.map((tool) => tool.name));
  const server = new Server(
    { name: manifest.server.name, version },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: structuredClone(manifest.tools),
  }));
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (!advertisedTools.has(request.params.name)) {
      return toolError(`Unknown Vision Bridge tool: ${request.params.name}`);
    }
    try {
      return await backend.callTool(request.params);
    } catch (error) {
      if (error instanceof VisionBridgeStartupError) {
        return toolError(
          "Vision Bridge Python backend is unavailable. " + error.message,
        );
      }
      if (error instanceof VisionBridgeRequestDeadlineError) {
        return toolError("Vision Bridge request deadline exceeded.");
      }
      return toolError("Vision Bridge tool call failed.");
    }
  });
  server.onclose = () => {
    void backend.close();
  };
  return server;
}

export async function serveVisionBridge({
  command,
  args,
  cwd,
  environment = process.env,
  input = process.stdin,
  output = process.stdout,
  manifest,
  version,
  telemetry = emitTelemetry,
} = {}) {
  const resolvedManifest = manifest || await readManifest();
  const resolvedVersion = version || resolvedManifest.contract_version;
  const backend = new VisionBridgeBackend({
    command,
    args,
    cwd,
    environment,
    startupTimeoutMs: startupTimeoutMs(environment),
    requestTimeoutMs: requestTimeoutMs(environment),
    telemetry,
  });
  const server = createVisionBridgeServer({
    manifest: resolvedManifest,
    version: resolvedVersion,
    backend,
  });
  await server.connect(new StdioServerTransport(input, output));
  void backend.start().catch(() => undefined);
  return { backend, server };
}

export function emitTelemetry(event, fields = {}, output = process.stderr) {
  const payload = { component: "vision-bridge", event };
  for (const [key, value] of Object.entries(fields)) {
    if (typeof value === "string" && /^[a-z0-9_-]{1,64}$/i.test(value)) {
      payload[key] = value;
    } else if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) {
      payload[key] = value;
    }
  }
  output.write(`${JSON.stringify(payload)}\n`);
}

function withRequestDeadline(params, { deadlineUnixMs, requestId }) {
  const existingMeta = params._meta && typeof params._meta === "object" ? params._meta : {};
  return {
    ...params,
    _meta: {
      ...existingMeta,
      [DEADLINE_META_KEY]: {
        deadline_unix_ms: deadlineUnixMs,
        request_id: requestId,
      },
    },
  };
}

function isDeadlineToolResult(result) {
  if (!result || result.isError !== true || !Array.isArray(result.content)) {
    return false;
  }
  return result.content.some(
    (item) => item?.type === "text" && item.text === "Vision Bridge request deadline exceeded",
  );
}

function positiveInteger(value, fallback) {
  const configured = Number.parseInt(value || "", 10);
  return Number.isSafeInteger(configured) && configured > 0 ? configured : fallback;
}

function toolError(text) {
  return {
    content: [{ type: "text", text }],
    isError: true,
  };
}

function startupError(error, timeoutMs) {
  if (error instanceof VisionBridgeStartupError) {
    return error;
  }
  if (isTimeoutError(error)) {
    return new VisionBridgeStartupError(
      `Python backend was not ready within ${timeoutMs}ms. ` +
        "Run the one-time Vision Bridge preparation command, then restart the MCP client.",
    );
  }
  return new VisionBridgeStartupError(
    "Python backend failed its deterministic startup check. " +
      "Run the one-time Vision Bridge preparation command, then restart the MCP client.",
  );
}

function errorKind(error) {
  if (isTimeoutError(error)) {
    return "timeout";
  }
  if (error instanceof VisionBridgeStartupError) {
    return "startup";
  }
  return "transport";
}

function isTimeoutError(error) {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.name === "TimeoutError" || error.code === "ETIMEDOUT" || /timed? out/i.test(error.message);
}

function withTimeout(promise, timeoutMs, onTimeout) {
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => {
      void onTimeout?.();
      const error = new Error(`Python backend did not become ready within ${timeoutMs}ms`);
      error.name = "TimeoutError";
      rejectPromise(error);
    }, timeoutMs);
    timer.unref();
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolvePromise(value);
      },
      (error) => {
        clearTimeout(timer);
        rejectPromise(error);
      },
    );
  });
}

async function readManifest() {
  const { readFile } = await import("node:fs/promises");
  const { dirname, resolve } = await import("node:path");
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  return JSON.parse(await readFile(resolve(root, "contract", "manifest.json"), "utf8"));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  serveVisionBridge().catch((error) => {
    const message = error instanceof Error ? error.message : "Vision Bridge failed to start.";
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
  });
}
