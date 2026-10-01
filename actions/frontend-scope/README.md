# Frontend change scope

A dependency-free composite action that decides which existing frontend checks a change needs. It starts no additional jobs and never reads the private installation credentials. Run it on a GitHub-hosted Linux runner after checkout with full history and Node 22 setup.

```yaml
- uses: actions/checkout@REVIEWED_COMMIT_SHA
  with:
    fetch-depth: 0
    persist-credentials: false
- uses: actions/setup-node@REVIEWED_COMMIT_SHA
  with:
    node-version: 22
- id: scope
  uses: ./.github/actions/frontend-scope
  with:
    config: .github/frontend-ci.json
- if: steps.scope.outputs.code == 'true'
  run: npm run lint
```

Replace placeholders with reviewed immutable action commits. A reviewed local bundle is supported; consumers can also reference `dehanz13/runner-kit/actions/frontend-scope@REVIEWED_FULL_COMMIT_SHA`. Pin the reviewed release commit, not a movable branch. The toolkit is distributed under the MIT license.

## Policy

```json
{
  "schema_version": 1,
  "tests_ignore_prefixes": ["manual/"],
  "code_extensions": [".ts", ".tsx", ".js", ".json"],
  "code_prefixes": ["assets/"],
  "workflow_prefixes": [".github/"]
}
```

Prefixes are literal repository-relative directories ending in `/`. Extensions are literal lowercase suffixes. No regex, glob, template or command execution is accepted. Each list contains at most 64 unique entries. The policy file is bounded to 16 KiB and must be a regular file, not a final symlink. Treat the policy as reviewed code: a malicious contributor who can change their own workflow can change its checks too.

| Output | Meaning |
|---|---|
| `tests` | True unless every changed path is under a proven unread directory |
| `code` | True when a changed path has a configured extension or prefix |
| `workflows` | True when a changed path has a configured workflow prefix |
| `reason` | Fixed identifier describing selection or full-run fallback |

Only pull-request events may narrow checks. Manual dispatch and other events select everything. Missing/bad policy, missing/invalid base SHA, unavailable diff, invalid encoding and empty diff also select everything. A failure to write Actions outputs fails the step. Unknown directories still run tests; customers must separately maintain the complete set of inputs read by their compiler/build tools in the code policy.

Git diffs use NUL separators and disable rename detection so both the deleted and added path are considered. Git output is bounded to 8 MiB and 10 seconds; failure runs the full check set. The selector disables external diffs/text conversion and does not inherit `GIT_*` variables or global/system Git configuration. It logs boolean decisions, a fixed reason and a path count, not filenames, diff contents or parser diagnostics.

Keep cheap repository-policy checks outside these output conditions. Do not add workflow-level path filters to a required status merely because steps can be skipped. Trigger cadence, check names, permissions, deployment policy and runner selection stay under the customer's workflow control.

## One configuration source

An installation can add a `frontend_scope` section and a trusted `frontend-config` binding selecting it in its existing private config. Use `runner_kit.frontend.render_scope` or:

```sh
python3 -m runner_kit --config /private/installation/config.json render-frontend-scope
```

Review the successful output, then save it as the customer's checked-in scope JSON. It is a generated non-secret projection, not a second secret file. Updating private settings does not update GitHub automatically: regenerate, review and merge the projection. Never upload the private config. Node bootstrap, job timeout and GitHub environment secrets remain workflow/platform settings in this first slice; it is not yet a full workflow generator.

## Validation and limits

Run `node --test actions/frontend-scope/scope.test.mjs` from the toolkit root. Tests create real temporary Git histories and execute the CLI, including rename-out, deletion, unusual filenames, config changes, failure fallback and Actions output handling. The bundle includes these tests so customers can run the same checks in their own CI. Customer tests should additionally verify that skipped directories are not read by their own suites.

This tool chooses checks; it is not a frontend test runner, security scanner, VM manager or network sandbox. Preserving skips does not establish additional cost savings. Measure hosted runs after rollout. Do not infer remote CI success from local tests.

References: [Git diff formats and options](https://git-scm.com/docs/git-diff), [GitHub composite actions](https://docs.github.com/en/actions/tutorials/create-actions/create-a-composite-action).
