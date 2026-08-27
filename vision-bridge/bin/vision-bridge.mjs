#!/usr/bin/env node

import { accessSync, constants, realpathSync } from "node:fs";
import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { serveVisionBridge } from "../src/npm-server.mjs";

export function packageRoot(importMetaUrl = import.meta.url) {
  return resolve(dirname(fileURLToPath(importMetaUrl)), "..");
}

export function buildUvArgs(root = packageRoot()) {
  return [
    "run",
    "--quiet",
    "--offline",
    "--locked",
    "--no-sync",
    "--no-default-groups",
    "--project",
    root,
    "vision-bridge",
  ];
}

export function buildPrepareUvArgs(root = packageRoot()) {
  return [
    "sync",
    "--quiet",
    "--locked",
    "--no-default-groups",
    "--project",
    root,
  ];
}

export function isMainModule(
  argvPath = process.argv[1],
  importMetaUrl = import.meta.url,
) {
  if (!argvPath) {
    return false;
  }
  try {
    return realpathSync(argvPath) === realpathSync(fileURLToPath(importMetaUrl));
  } catch {
    return resolve(argvPath) === fileURLToPath(importMetaUrl);
  }
}

function isExecutable(path) {
  try {
    accessSync(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export function findUvCommand(
  environment = process.env,
  { platform = process.platform, canExecute = isExecutable } = {},
) {
  if (environment.VISION_BRIDGE_UV_COMMAND) {
    return environment.VISION_BRIDGE_UV_COMMAND;
  }
  const executable = platform === "win32" ? "uv.exe" : "uv";
  const candidates = [
    environment.HOME && resolve(environment.HOME, ".local", "bin", executable),
    environment.HOME && resolve(environment.HOME, ".cargo", "bin", executable),
    environment.USERPROFILE && resolve(environment.USERPROFILE, ".local", "bin", executable),
  ].filter(Boolean);
  return candidates.find((candidate) => canExecute(candidate)) || executable;
}

export function isPrepareCommand(argv = process.argv.slice(2)) {
  return argv.length === 1 && argv[0] === "--prepare";
}

export async function runVisionBridge({
  command,
  environment = process.env,
  root = packageRoot(),
  prepare = false,
} = {}) {
  const uvCommand = command || findUvCommand(environment);
  if (!prepare) {
    await serveVisionBridge({
      command: uvCommand,
      args: buildUvArgs(root),
      cwd: root,
      environment,
    });
    return 0;
  }
  return runPrepare(uvCommand, buildPrepareUvArgs(root), root, environment);
}

function runPrepare(command, args, root, environment) {
  return new Promise((resolveExitCode) => {
    const child = spawn(command, args, {
      cwd: root,
      env: environment,
      stdio: "inherit",
    });
    child.once("error", (error) => {
      if (error.code === "ENOENT") {
        process.stderr.write(
          "vision-bridge requires uv. Install uv from https://docs.astral.sh/uv/ and run the one-time Vision Bridge preparation command.\n",
        );
        resolveExitCode(127);
        return;
      }
      process.stderr.write("vision-bridge preparation could not start.\n");
      resolveExitCode(1);
    });
    child.once("exit", (code) => resolveExitCode(code ?? 1));
  });
}

if (isMainModule()) {
  const prepare = isPrepareCommand();
  if (process.argv.length > 2 && !prepare) {
    process.stderr.write("usage: vision-bridge [--prepare]\n");
    process.exitCode = 2;
  } else {
    runVisionBridge({
      command: findUvCommand(process.env),
      prepare,
    }).then((code) => {
      process.exitCode = code;
    }).catch((error) => {
      const message = error instanceof Error ? error.message : "Vision Bridge failed to start.";
      process.stderr.write(`${message}\n`);
      process.exitCode = 1;
    });
  }
}
