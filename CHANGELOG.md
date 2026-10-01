# Changelog

## 0.1.0

First public release of the toolkit building blocks. GitHub-hosted CI remains the default execution environment.

### Added

- Dependency-free frontend scope action with reviewed per-repository policy, conservative full-check fallback and real Git-history tests.
- Private configuration loader and CLI with owner/permission checks, bounded input, duplicate-key rejection and value-free inspection.
- Non-secret frontend-policy and pinned Lima-profile exporters.
- Explicit pilot cleanup leases with preview, cancellation, identity validation and bounded cleanup commands.
- Installable Python CLI and hosted tests for the supported Python baseline and current runtime, plus Node 22 action tests.

### Limits

- No registered GitHub runner, unattended VM supervisor, externally enforced networking or production-ready home runner pool.
- No password-manager adapter, cloud database, knowledge bank, workflow dashboard or automatic private-config synchronization.
- A scope policy is reviewed repository code, not an authorization boundary against a contributor who can edit their workflow.
- Pilot tools remain experimental host-side primitives. They require the documented isolation and operator controls before any untrusted workload is admitted.
- This release makes no cost-savings or availability guarantee.
