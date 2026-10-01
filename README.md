# Runner Kit

Small, reusable building blocks for GitHub Actions check selection, private configuration and experimental disposable-runner lifecycle tools. GitHub-hosted runners remain the default.

Version 0.1.0 is the first building-block release. See the [changelog](CHANGELOG.md), [security boundaries](SECURITY.md) and [MIT license](LICENSE).

## Available now

A dependency-free frontend action selects checks using a reviewed customer policy, conservatively runs everything on uncertainty and needs no secrets or package installation. A Python configuration module provides one private source for settings, component environment bindings and local secret slots. It checks file ownership and permissions, rejects ambiguous JSON and exposes a value-free inspection CLI. A pilot exporter renders a pinned, mount-free Lima definition. A host-side cleanup tool leases one explicitly adopted VZ pilot and previews or applies due cleanup. No unattended VM supervisor, registered runner, cloud deployment, dashboard or password-manager integration is implemented yet.

Requires Python 3.11+ on macOS or Linux. Run from this directory with your Python 3.11+ executable:

```sh
python3 -m runner_kit --config ../.local/config.json init --workspace ..
python3 -m runner_kit --config ../.local/config.json check
python3 -m runner_kit --config ../.local/config.json describe
python3 -m unittest discover -s tests -v
```

Initialization creates empty secret slots with owner-only access and refuses to overwrite an existing file. Skip `init` when an installation already exists. `check` validates structure; it does not verify credentials, provider permissions or deployed services.

For an installed CLI, use a dedicated Python environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/runner-kit --help
```

Python 3.11+ is required; the frontend action requires Node 22 and Git. GitHub consumers should pin the action to a reviewed full commit SHA rather than relying on a movable tag. The [action guide](actions/frontend-scope/README.md) explains configuration and integration. No package is published to PyPI by this release.

- [Configuration and secrets](docs/configuration.md)
- [Lima lifecycle pilot and its isolation limits](docs/lima-pilot.md)
- [Pilot cleanup leases](docs/pilot-cleanup.md)
- [External network isolation design and acceptance tests](docs/network-isolation.md)
- [Frontend change-scope action and customer configuration](actions/frontend-scope/README.md)
- [RunsOn provider evaluation](docs/providers/runs-on.md)

## Planned capabilities

Generic Linux VM recipes; Node/browser and Rust profiles; disposable service tests; runner lifecycle supervision; benchmark reports in Excalidraw, HTML and raw data; optional workflow dashboard. These are separate increments with their own validation before activation.

## Publication boundary

This repository contains generic source and synthetic examples under the MIT license. Operators supply their own infrastructure and credentials. Contributions use GitHub-hosted CI and cannot access an operator's private runner pool.

Keep registered runners, VM state, private caches, credentials, operational inventory and real archives outside this repository. Review extracted source, dependencies, licenses and generated artifacts before publication.
