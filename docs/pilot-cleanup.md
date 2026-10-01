# Pilot cleanup leases

The pilot controller is a host-side cleanup tool for one explicitly adopted VZ pilot. It never starts a VM, runs guest code, registers a GitHub runner or installs a scheduler. Use it only for the trusted lifecycle pilot while network isolation is being developed.

## One installation file

Add the `pilot_control` settings and `pilot-controller` binding from `runner_kit/defaults.json` to an existing installation's private config. New installations receive them during `init`. The executable path must point to the installed, trusted `limactl`; it may differ between macOS and Linux installations. No shell text is accepted as arguments. A configuration file is trusted operator input, not a sandbox for malicious administrators.

The controller derives the pilot namespace as `<paths.state>/lima` and its journal as `<paths.state>/pilot-control`. Both must be real, owner-only directories. Instance names must start with `rk-`. An instance name is not evidence of ownership: explicit arming records the directory identity, VM identifier and VM-definition hash.

Default deadline: 900 seconds. Maximum: 3600 seconds. A config edit cannot extend an existing lease. Do not move the state directory, rename the instance, edit its definition or use other lifecycle tools concurrently with reconciliation. Such changes can strand a lease and require operator review.

## Commands

Run these on the host that owns the Lima installation, from the toolkit directory:

```sh
# Existing pilot must be stopped. Refuses to replace an existing lease.
python3 -m runner_kit --config ../.local/config.json pilot-arm

# Preview only. An unexpired lease is kept.
python3 -m runner_kit --config ../.local/config.json pilot-reap

# Mark completion/cancellation; this alone does not stop the VM.
python3 -m runner_kit --config ../.local/config.json pilot-cancel

# Stop/delete the exact leased VM only when cancellation or expiry makes it due.
python3 -m runner_kit --config ../.local/config.json pilot-reap --apply
```

Arming authorizes later deletion of that exact pilot. Store no valuable data in it. Preview creates/checks the controller's private lock directory but makes no VM changes.

## Failure behavior

- Lease writes use an atomic replacement, owner-only permissions and fsync. A nonblocking host file lock serializes controller calls.
- A changed host boot identity, clock rollback, either elapsed monotonic deadline or elapsed wall-clock deadline makes cleanup due. This deliberately prefers retiring a pilot over extending its lifetime after clock anomalies.
- A changed VM/config/directory identity refuses deletion and retains the journal. Same-UID/root host compromise is outside this protection.
- A running owned VM first receives a bounded graceful stop. Failure permits a bounded force-stop of that same identity. Deletion requires confirmed stopped state and identity revalidation.
- Unknown VM status, failed inventory, unconfirmed deletion, unsafe files and command timeout never become successful cleanup. The lease remains for retry or investigation.
- If deletion completed before the process crashed, the next invocation clears the lease only after both Lima inventory and filesystem confirm absence. Repeated cleanup is harmless.
- Only the current lease and latest successful cleanup receipt are retained. Image caches, unrelated VMs, shared volumes and source repositories are never pruned.

## What this does not guarantee yet

Deadline enforcement happens **when the reaper runs**. There is no background watchdog, startup admission lock, automatic GitHub cancellation hook or full job supervisor. Unit tests simulate reboot and failure conditions; that does not prove automatic recovery after a real host reboot. A future protected watchdog must reconcile before admitting work and keep working when the job/supervisor process dies.

This pilot currently requires VZ identity files. The renderer's QEMU option does not imply QEMU cleanup support. No network safety claim follows from successful cleanup. See [network isolation](network-isolation.md).
