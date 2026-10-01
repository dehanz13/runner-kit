# Security boundaries

Keep credentials and installation state outside this repository. Do not put secrets, personal records, private inventories, registered runner files, writable VM images or operational logs in issues or pull requests.

The frontend action runs on hosted CI with a reviewed non-secret policy. The policy and workflow are editable together: ordinary protected review remains required. A successful action test does not authorize running a contributor's code on private infrastructure.

The Python CLI initially supports an owner-only local secrets file. It is plaintext at rest; use an encrypted disk and backups. Environment-variable injection is not secret storage. Export only the explicitly selected non-secret policy/profile, never the authoritative private config.

Pilot lifecycle and cleanup commands are experimental. The toolkit does not install or certify network isolation, a watchdog, a runner fleet or production credentials. Follow the isolation limits in the [pilot guide](docs/lima-pilot.md) and [network design](docs/network-isolation.md).

For a suspected vulnerability, use GitHub's private vulnerability reporting for this repository when available. Do not disclose credentials or an exploitable private deployment in a public issue. There is no guaranteed response-time or support SLA for this initial release.
