import assert from "node:assert/strict";
import { test } from "node:test";
import { execFileSync, spawnSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { decideScope } from "./scope.mjs";

const policy = {
  schema_version: 1,
  tests_ignore_prefixes: ["notes/"],
  code_extensions: [".ts", ".json"],
  code_prefixes: ["static/"],
  workflow_prefixes: [".github/"],
};

function repo(t) {
  const cwd = mkdtempSync(join(tmpdir(), "frontend-scope-"));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([name]) => !name.startsWith("GIT_")),
  );
  Object.assign(env, {
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_AUTHOR_NAME: "test",
    GIT_AUTHOR_EMAIL: "test@example.invalid",
    GIT_COMMITTER_NAME: "test",
    GIT_COMMITTER_EMAIL: "test@example.invalid",
  });
  const git = (...args) =>
    execFileSync("git", args, {
      cwd,
      env,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  const put = (name, value) => {
    mkdirSync(join(cwd, name, ".."), { recursive: true });
    writeFileSync(join(cwd, name), value);
  };
  git("init", "-q");
  put("src/app.ts", "export default 1;\n");
  put("scope.json", JSON.stringify(policy));
  git("add", ".");
  git("commit", "-qm", "base");
  const baseSha = git("rev-parse", "HEAD");
  const commit = () => {
    git("add", ".");
    git("commit", "-qm", "change");
  };
  const decide = (extra = {}) =>
    decideScope({
      cwd,
      configPath: "scope.json",
      eventName: "pull_request",
      baseSha,
      ...extra,
    });
  return { cwd, git, put, commit, decide, baseSha };
}

test("a documentation-only diff skips expensive checks using the supplied policy", (t) => {
  const r = repo(t);
  r.put("notes/release.md", "prose");
  r.commit();
  assert.deepEqual(r.decide(), {
    tests: false,
    code: false,
    workflows: false,
    reason: "changed_paths",
    changed_files: 1,
  });
});

test("moving source into an ignored folder still runs code and tests", (t) => {
  const r = repo(t);
  mkdirSync(join(r.cwd, "notes"));
  r.git("mv", "src/app.ts", "notes/app.md");
  r.commit();
  assert.deepEqual(r.decide(), {
    tests: true,
    code: true,
    workflows: false,
    reason: "changed_paths",
    changed_files: 2,
  });
});

test("workflow files select workflow and unit checks", (t) => {
  const r = repo(t);
  r.put(".github/workflows/verify.yml", "name: verify");
  r.commit();
  assert.deepEqual(r.decide(), {
    tests: true,
    code: false,
    workflows: true,
    reason: "changed_paths",
    changed_files: 1,
  });
});

test("an unfamiliar directory still runs tests", (t) => {
  const r = repo(t);
  r.put("new-feature/file.custom", "data");
  r.commit();
  assert.equal(r.decide().tests, true);
});

test("deleting source runs code checks", (t) => {
  const r = repo(t);
  r.git("rm", "src/app.ts");
  r.commit();
  assert.equal(r.decide().code, true);
});

test("newlines and workflow-command-like filenames stay data and are not logged", (t) => {
  const r = repo(t);
  r.put("notes/one\n::error::not-a-command.md", "data");
  r.commit();
  assert.deepEqual(r.decide(), {
    tests: false,
    code: false,
    workflows: false,
    reason: "changed_paths",
    changed_files: 1,
  });
});

test("manual dispatch always selects all checks", (t) => {
  const r = repo(t);
  r.put("notes/a.md", "data");
  r.commit();
  assert.deepEqual(r.decide({ eventName: "workflow_dispatch" }), {
    tests: true,
    code: true,
    workflows: true,
    reason: "full_event",
    changed_files: null,
  });
});

test("an absent comparison, invalid base, or empty diff cannot skip checks", (t) => {
  const r = repo(t);
  for (const [baseSha, reason] of [
    [undefined, "invalid_base"],
    ["$(touch marker)", "invalid_base"],
    ["f".repeat(40), "diff_unavailable"],
    [r.baseSha, "empty_diff"],
  ]) {
    assert.deepEqual(r.decide({ baseSha }), {
      tests: true,
      code: true,
      workflows: true,
      reason,
      changed_files: null,
    });
  }
});

test("malformed policy runs everything without leaking its contents", (t) => {
  const r = repo(t);
  r.put("scope.json", "FAKE_SECRET_CANARY");
  assert.deepEqual(r.decide(), {
    tests: true,
    code: true,
    workflows: true,
    reason: "invalid_policy",
    changed_files: null,
  });
});

test("another customer changes scope through configuration alone", (t) => {
  const r = repo(t);
  r.put(
    "scope.json",
    JSON.stringify({
      ...policy,
      tests_ignore_prefixes: ["manual/"],
      code_prefixes: ["assets/"],
    }),
  );
  r.git("add", ".");
  r.git("commit", "-qm", "customer policy");
  const baseSha = r.git("rev-parse", "HEAD");
  r.put("manual/a.md", "data");
  r.commit();
  assert.deepEqual(r.decide({ baseSha }), {
    tests: false,
    code: false,
    workflows: false,
    reason: "changed_paths",
    changed_files: 1,
  });
});

test("real CLI emits Actions outputs without using filenames as commands", (t) => {
  const r = repo(t);
  r.put("src/new.ts", "export default 2");
  r.commit();
  const output = join(r.cwd, "outputs");
  writeFileSync(output, "");
  const result = spawnSync(
    process.execPath,
    [
      fileURLToPath(
        new URL("./scope.mjs", import.meta.url),
      ),
      "scope.json",
    ],
    {
      cwd: r.cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        SCOPE_EVENT_NAME: "pull_request",
        SCOPE_BASE_SHA: r.baseSha,
        GITHUB_OUTPUT: output,
      },
    },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(
    readFileSync(output, "utf8"),
    "tests=true\ncode=true\nworkflows=false\nreason=changed_paths\n",
  );
  assert.equal(JSON.parse(result.stdout).changed_files, 1);
});

test("failure to write Actions outputs fails the step", (t) => {
  const r = repo(t);
  const result = spawnSync(
    process.execPath,
    [
      fileURLToPath(
        new URL("./scope.mjs", import.meta.url),
      ),
      "scope.json",
    ],
    {
      cwd: r.cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        SCOPE_EVENT_NAME: "workflow_dispatch",
        SCOPE_BASE_SHA: "",
        GITHUB_OUTPUT: r.cwd,
      },
    },
  );
  assert.equal(result.status, 1);
});
