import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type WorkerPolicy = { project: string; workspace: string; source: string; progress: string };

function pathWithoutLinks(candidate: string): string {
  const absolutePath = path.resolve(candidate);
  const parsedPath = path.parse(absolutePath);
  let currentPath = parsedPath.root;
  for (const component of absolutePath.slice(parsedPath.root.length).split(path.sep)) {
    if (!component) continue;
    currentPath = path.join(currentPath, component);
    try {
      const information = lstatSync(currentPath);
      if (information.isSymbolicLink()) throw new Error("Linked paths are not permitted");
      if (information.isFile() && information.nlink > 1) throw new Error("Hard linked files are not permitted");
      if (realpathSync.native(currentPath).toLowerCase() !== currentPath.toLowerCase()) {
        throw new Error("Redirected paths are not permitted");
      }
    } catch (error: any) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  return absolutePath;
}

function isInside(candidate: string, directory: string): boolean {
  const relativePath = path.relative(directory, candidate);
  return relativePath === "" || (!relativePath.startsWith(".." + path.sep) && relativePath !== ".." && !path.isAbsolute(relativePath));
}

export default function workerPermissions(pi: ExtensionAPI) {
  const policy: WorkerPolicy = JSON.parse(process.env.PI_KIT_WORKER_POLICY || "null");
  if (!policy || !path.isAbsolute(policy.workspace) || !path.isAbsolute(policy.source) || !path.isAbsolute(policy.progress)) {
    throw new Error("A complete worker policy is required");
  }
  const workspace = pathWithoutLinks(policy.workspace);
  const source = pathWithoutLinks(policy.source);
  const progress = pathWithoutLinks(policy.progress);
  if (!isInside(source, workspace) || source === workspace || isInside(progress, workspace)) {
    throw new Error("Worker paths do not match the isolated workspace policy");
  }

  function evaluatePermission(toolName: string, input: any, parentToolCallId?: string): boolean {
    if (parentToolCallId || !["read", "edit", "write"].includes(toolName)) return false;
    if (!input || typeof input.path !== "string" || input.path.includes("\0")) return false;
    try {
      const candidate = pathWithoutLinks(path.resolve(workspace, input.path));
      if (toolName === "read") return isInside(candidate, workspace) || candidate === progress;
      return candidate === source || candidate === progress;
    } catch {
      return false;
    }
  }

  pi.on("session_start", async () => {
    pi.setActiveTools(["read", "edit", "write"]);
  });

  pi.on("tool_call", async (event: any) => {
    if (!evaluatePermission(event.toolName, event.input, event.parentToolCallId)) {
      return { block: true, reason: "This worker may only read its workspace and edit its assigned source and progress file" };
    }
  });

  pi.registerCommand("kit-permission-check", {
    description: "Verify an isolated worker permission without contacting a model",
    handler: async (argument, context) => {
      let result = { nonce: "", allowed: false };
      try {
        const request = JSON.parse(argument);
        result = { nonce: String(request.nonce), allowed: evaluatePermission(request.tool, request.input, request.parentToolCallId) };
      } catch {}
      context.ui.notify("pi-kit-permission:" + JSON.stringify(result), "info");
    },
  });
}
