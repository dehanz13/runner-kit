/** Conservative, dependency-free change selection. Never executes repository scripts. */
import { execFileSync } from "node:child_process";
import {
  appendFileSync,
  closeSync,
  constants,
  fstatSync,
  openSync,
  readFileSync,
} from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const full = (reason) => ({
  tests: true,
  code: true,
  workflows: true,
  reason,
  changed_files: null,
});
const fields = [
  "schema_version",
  "tests_ignore_prefixes",
  "code_extensions",
  "code_prefixes",
  "workflow_prefixes",
];

function readPolicy(file) {
  const fd = openSync(
    file,
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
  );
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.size > 16384) throw new Error("policy_size");
    const value = JSON.parse(readFileSync(fd, "utf8"));
    if (
      !value ||
      Array.isArray(value) ||
      value.schema_version !== 1 ||
      Object.keys(value).length !== fields.length ||
      fields.some((field) => !(field in value))
    )
      throw new Error("policy_schema");
    for (const field of fields.slice(1)) {
      const list = value[field];
      if (
        !Array.isArray(list) ||
        list.length > 64 ||
        new Set(list).size !== list.length
      )
        throw new Error("policy_list");
      for (const item of list) {
        if (
          typeof item !== "string" ||
          item.length > 128 ||
          (field === "code_extensions"
            ? !/^\.[a-z0-9]+$/.test(item)
            : !/^(?:[a-zA-Z0-9_.-]+\/)+$/.test(item) ||
              item.split("/").some((part) => part === "." || part === ".."))
        )
          throw new Error("policy_path");
      }
    }
    return value;
  } finally {
    closeSync(fd);
  }
}

/**
 * A missing/invalid policy or uncertain comparison RUNS checks. Reasons are
 * fixed identifiers; neither filenames nor parser/git diagnostics enter logs.
 * Configuration is reviewed code, not protection against a malicious PR that
 * can edit its own workflow. A protected review policy remains necessary.
 */
export function decideScope({ cwd, configPath, eventName, baseSha }) {
  let policy;
  try {
    policy = readPolicy(resolve(cwd, configPath));
  } catch {
    return full("invalid_policy");
  }
  if (eventName !== "pull_request") return full("full_event");
  if (!/^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/.test(baseSha ?? ""))
    return full("invalid_base");
  let paths;
  try {
    // Disabling rename detection reports both the deleted old path and the
    // added new path. NUL separators preserve spaces/newlines in filenames.
    const env = Object.fromEntries(
      Object.entries(process.env).filter(([name]) => !name.startsWith("GIT_")),
    );
    Object.assign(env, {
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_CONFIG_NOSYSTEM: "1",
    });
    const raw = execFileSync(
      "git",
      [
        "--no-optional-locks",
        "-c",
        "core.fsmonitor=false",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        `${baseSha}...HEAD`,
        "--",
      ],
      {
        cwd,
        env,
        timeout: 10000,
        maxBuffer: 8 * 1024 * 1024,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    const text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    if (text && !text.endsWith("\0")) return full("invalid_diff");
    paths = text ? text.slice(0, -1).split("\0") : [];
    if (paths.some((path) => !path)) return full("invalid_diff");
  } catch {
    return full("diff_unavailable");
  }
  if (paths.length === 0) return full("empty_diff");
  return {
    tests: paths.some(
      (path) =>
        !policy.tests_ignore_prefixes.some((prefix) => path.startsWith(prefix)),
    ),
    code: paths.some(
      (path) =>
        policy.code_extensions.some((extension) => path.endsWith(extension)) ||
        policy.code_prefixes.some((prefix) => path.startsWith(prefix)),
    ),
    workflows: paths.some((path) =>
      policy.workflow_prefixes.some((prefix) => path.startsWith(prefix)),
    ),
    reason: "changed_paths",
    changed_files: paths.length,
  };
}

export function emit(result, outputPath) {
  // Output keys/values are fixed booleans and identifiers, never caller text.
  if (outputPath)
    appendFileSync(
      outputPath,
      ["tests", "code", "workflows", "reason"]
        .map((key) => `${key}=${result[key]}\n`)
        .join(""),
    );
  return JSON.stringify(result);
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  try {
    console.log(
      emit(
        decideScope({
          cwd: process.cwd(),
          configPath: process.argv[2],
          eventName: process.env.SCOPE_EVENT_NAME,
          baseSha: process.env.SCOPE_BASE_SHA,
        }),
        process.env.GITHUB_OUTPUT,
      ),
    );
  } catch {
    // Failure to publish outputs must fail the step, not silently skip consumers.
    console.error("frontend-scope: cannot publish the decision");
    process.exitCode = 1;
  }
}
