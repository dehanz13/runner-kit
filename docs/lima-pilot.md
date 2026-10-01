# Lima lifecycle pilot

The `render-lima` command exports a small, pinned Linux VM definition from the installation's `pilot_vm` settings. It does not create a VM, register a GitHub runner, execute repository code or implement a disposable runner supervisor.

```sh
python3 -m runner_kit --config ../.local/config.json render-lima > pilot.yaml
limactl validate pilot.yaml
```

JSON output is valid YAML and is accepted by Lima. The exporter selects only the VM fields it understands. It excludes central secrets and arbitrary provisioning commands. The CLI fails if `vm-pilot` is missing from an older installation; initialization never overwrites that installation. Add the `pilot_vm` section and `vm-pilot` component from the current initialization template through a reviewed config update.

## Configuration

| Setting | Meaning |
|---|---|
| `vm_type` | `vz` or `qemu`; the operator must check host support |
| `arch` | `x86_64` or `aarch64`; must match the selected image and hardware plan |
| `cpus` | Integer 1–4 for this bounded pilot |
| `memory_mib` | Integer 1024–16384 MiB; check host headroom before allocating |
| `disk_gib` | Integer 8–64 GiB virtual disk limit, not observed physical usage |
| `image_url` | Approved HTTPS Ubuntu cloud-image URL, no embedded credentials/query |
| `image_digest` | Required SHA-256 content pin; no unpinned fallback |

The initial template chooses Ubuntu 24.04 minimal, 2 vCPUs, 2 GiB RAM and a 12 GiB virtual disk. Update the installation file to change allocations or image pins; changing packaged defaults does not alter existing installations. An image pin provides reproducibility, not a promise that the image has no vulnerabilities. Refresh images deliberately and verify their source/digest before registration.

## Isolation limits

Plain mode disables Lima filesystem mounts, its guest agent, dynamic port forwarding and bundled containerd. The export also disables SSH-agent forwarding, importing the host user's public keys and proxy-environment propagation. [Lima plain mode](https://lima-vm.io/docs/config/plain/)

Use a dedicated `LIMA_HOME` outside all job guests so existing global Lima configuration does not modify this definition. Validate the rendered and effective configurations, not just the input file. Do not mount the central config, host home, project folders, Docker socket or SSH agent.

**This is not yet a network sandbox.** Lima's normal user networking exposes a host gateway; plain mode does not establish an external egress firewall. A guest-side firewall is not sufficient when job code can obtain guest root. [Lima networking](https://lima-vm.io/docs/config/network/user/)

Until network controls and disposable-state supervision are independently verified, run only trusted lifecycle probes. No GitHub registration or untrusted repository jobs. Test boot, host-mount absence, absence of forwarded credentials, graceful stop/restart, destruction, recreation and cross-instance canaries. Stop the pilot after testing; report allocated and actual disk usage separately.

## Validation status

Unit tests cover exclusion of synthetic secret canaries, config-derived resources and rejection of unsafe image inputs, excess allocations and mount overrides. Live lifecycle evidence belongs in the operator's private report; this public guide does not certify a particular installation.
