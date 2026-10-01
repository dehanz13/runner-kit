# Configuration and local secrets

The local installation has one authoritative private JSON file. Set its location with `--config` or the bootstrap variable `RUNNER_KIT_CONFIG`. The public `runner_kit/defaults.json` is an initialization template with empty credentials; changing that template does not alter an existing installation.

## File layout

| Field | Purpose |
|---|---|
| `schema_version` | Currently integer `1` |
| `workspace_root` | Installation root; relative paths resolve from the config directory |
| `settings` | Nonsecret settings grouped by component purpose |
| `components` | Trust class, selected settings and environment bindings |
| `secrets.provider` | Currently only `local` is implemented |
| `secrets.values` | Private values indexed by stable aliases |

Use `${workspace}` for derived paths. For example, changing `workspace_root` updates `${workspace}/.archive` and `${workspace}/.state` together. No other interpolation, shell execution, `.env` sourcing or environment inheritance takes place.

Each component names the settings sections it needs. Ordinary environment bindings reference a setting such as `runner.vcpus`; secret bindings reference an alias such as `github_readonly_token`. An `isolated-job` cannot bind a central secret. Default component names describe future consumers; loading their configuration does not start those services.

## Trusted caller interface

```python
from runner_kit import Configuration

snapshot = Configuration.load(private_config_path)
settings = snapshot.settings_for("ci-worker")
environment = snapshot.environment_for("ci-worker")
```

`settings_for` returns a copy. `environment_for` returns only the declared variables, with no ambient process environment merged in. Its representation hides values, but indexing or converting it to a dictionary exposes them to the caller. Never log that dictionary. This module does not launch subprocesses; a future trusted launcher must explicitly construct its minimal execution environment and transport guest-safe settings without giving the guest the private file.

Reload with `Configuration.load` for each new invocation. A running service keeps its existing snapshot until an explicit reload/restart. Atomic replacement of the file with preserved ownership and permissions avoids partial reads. Do not place credentials in shell arguments, command history, tickets, benchmark artifacts or Git.

## Local file protection

The immediate parent directory must be owned by the current user with mode `0700`; the regular file must be owned by that user with mode `0600` or read-only `0400`. The loader rejects final symlinks, a symlink immediate parent, additional hard links, oversized files, duplicate keys, non-UTF-8 JSON and nonfinite numbers. It never silently repairs permissions. Error messages omit input values.

This is accidental-disclosure protection, not isolation from root or another process running as the same OS user. All trusted processes that can read the file can read all its secrets. Component selection is not an OS permission boundary. Keep the file on the trusted host or services VM under a dedicated account; never mount it in a job VM. Disk encryption and protected backups remain operational responsibilities.

The loader validates configuration structure, not provider privileges, network policy or every consumer's operational range. For example, resource and port bounds must be validated by the actual supervisor/dashboard before use. Credential-name checks help catch mistakes but are not a general secret detector. `check` can succeed with empty secret slots; accessing a component that needs one then fails with `SECRET_UNSET`.

## Multiple installations and future password manager

Each operator supplies their own private file and credentials. No shared global vault or credentials are embedded in this repository. The `local` provider is the only current implementation; selecting another provider fails explicitly. A later password-manager provider can resolve aliases at the same boundary, using a separately protected bootstrap identity and narrowly scoped access. It must never fall back silently to another credential source.

## GitHub and cloud configuration

GitHub evaluates job routing before a worker can read a local file. The local file therefore cannot directly drive a hosted job's `runs-on` selection. `render-frontend-scope` now exports an allowlisted nonsecret check-selection policy from `frontend_scope`. New installations receive a conservative template that skips no test directories; older installations add that section and the `frontend-config` binding explicitly. The checked-in policy is a derived copy and must be regenerated and reviewed deliberately. Automatic synchronization, runner routing and a complete workflow generator are not implemented.

Similarly, an AWS control plane cannot depend on a home machine being online to read credentials. A future cloud adapter must provision only the necessary secret references/values into its protected runtime store. This is controlled distribution from the installation configuration, not permission to copy the entire file to cloud runners. Existing GitHub/environment secrets and OIDC deployment identities stay under their current controls until an explicit integration is implemented.

## Validation evidence

The tests exercise permission failures, credential scoping, redacted diagnostics, independent installation files, reload behavior, cleanup leases and rejection of malformed input. The current local suite has 48 passing tests on macOS/Python 3.14.7. An earlier 27-test configuration/pilot-export suite also passed on an unregistered Ubuntu pilot/Python 3.12.3. Public CI runs the complete suite and installed-package smoke checks on Linux with Python 3.11 and 3.14; consult the exact commit's CI result for that evidence. Passing these tests does not certify VM network isolation or a GitHub runner deployment.
