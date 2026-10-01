"""Host-owned cleanup leases for a single trusted Lima pilot.

This module never starts VMs or runs guest commands. Reconciliation must be
invoked by an operator or, later, a separately installed watchdog. It is not
an unattended supervisor or a network isolation mechanism.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from .config import ConfigError, _decode, _private_directory, _read_private


def require(condition, code):
    if not condition:
        raise ConfigError(code, "Pilot control refused the operation; inspect the documented preconditions.")


def boot_id():
    if sys.platform == "darwin":
        try:
            raw = subprocess.check_output(["/usr/sbin/sysctl", "-n", "kern.boottime"], timeout=5, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError):
            raise ConfigError("PILOT_BOOT_ID", "Cannot determine the host boot identity.") from None
        match = re.search(rb"sec = (\d+), usec = (\d+)", raw)
        require(match is not None, "PILOT_BOOT_ID")
        raw = b":".join(match.groups())
    elif sys.platform.startswith("linux"):
        raw = Path("/proc/sys/kernel/random/boot_id").read_bytes().strip()
    else:
        raise ConfigError("PILOT_PLATFORM", "Pilot control supports macOS and Linux only.")
    return hashlib.sha256(raw).hexdigest()


class Lima:
    """Fixed argument lists; no shell, ambient credentials, or guest output."""

    def __init__(self, executable, home, timeout):
        self.executable, self.home, self.timeout = executable, home, timeout

    def _run(self, arguments, *, capture=False):
        environment = {"HOME": pwd.getpwuid(os.geteuid()).pw_dir,
                       "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
                       "LIMA_HOME": str(self.home), "LANG": "C", "LC_ALL": "C"}
        # A file keeps unexpectedly verbose CLI output out of memory and chat.
        # Only `list --format` is captured; its format excludes guest/config data.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([self.executable, *arguments], env=environment,
                                       stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       stdout=output if capture else subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                status = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ConfigError("PILOT_COMMAND_TIMEOUT", "A Lima operation timed out; the cleanup lease was retained.") from None
            require(status == 0, "PILOT_COMMAND_FAILED")
            output.seek(0)
            raw = output.read(65537) if capture else b""
            require(len(raw) <= 65536, "PILOT_INVENTORY_SIZE")
            return raw

    def status(self, name):
        # No target argument: Lima may exit successfully for an unknown name.
        # Parse an explicit inventory, and never interpret command failure as absence.
        raw = self._run(["list", "--format", "{{.Name}}\t{{.Status}}"], capture=True)
        try:
            entries = [line.split("\t") for line in raw.decode("utf-8").splitlines()]
        except UnicodeError:
            raise ConfigError("PILOT_INVENTORY", "Lima inventory was not valid UTF-8.") from None
        require(all(len(row) == 2 for row in entries), "PILOT_INVENTORY")
        require(len({row[0] for row in entries}) == len(entries), "PILOT_INVENTORY")
        return dict(entries).get(name)

    def stop(self, name, *, force=False):
        self._run(["stop", "--tty=false", *(["--force"] if force else []), name])

    def delete(self, name):
        self._run(["delete", "--tty=false", name])


class PilotControl:
    """Arm a stopped pilot once; cancel or reconcile its durable lease.

    A lease is an explicit adoption of the configured pilot, not discovery of
    arbitrary stale VMs. The private state is trusted host data; same-UID/root
    compromise is outside this module's protection. Do not manage its VM with
    other tools concurrently: the lock coordinates only this module's callers.
    """

    def __init__(self, config, *, driver=None, clock=time, get_boot_id=boot_id):
        selected = config.settings_for("pilot-controller")
        values = selected.get("pilot_control", {})
        require(set(values) == {"instance", "lima_executable", "lease_seconds", "command_timeout_seconds"}, "PILOT_SETTINGS")
        self.name = values["instance"]
        require(type(self.name) is str and re.fullmatch(r"rk-[a-z0-9][a-z0-9-]{0,39}", self.name), "PILOT_NAME")
        self.duration = values["lease_seconds"]
        timeout = values["command_timeout_seconds"]
        require(type(self.duration) is int and 1 <= self.duration <= 3600, "PILOT_DURATION")
        require(type(timeout) is int and 5 <= timeout <= 60, "PILOT_TIMEOUT")
        executable = values["lima_executable"]
        require(type(executable) is str and Path(executable).is_absolute() and "\0" not in executable, "PILOT_EXECUTABLE")
        state = Path(selected.get("paths", {}).get("state", ""))
        require(state.is_absolute(), "PILOT_STATE")
        self.home = state / "lima"
        self.directory = state / "pilot-control"
        self.target = self.home / self.name
        self.lease_path = self.directory / "lease.json"
        self.driver = driver or Lima(executable, self.home, timeout)
        self.clock, self.get_boot_id = clock, get_boot_id

    @contextmanager
    def _locked(self):
        _private_directory(self.home)
        require(self.home.resolve() == self.home, "PILOT_HOME_SYMLINK")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        _private_directory(self.directory)
        require(self.directory.resolve() == self.directory, "PILOT_STATE_SYMLINK")
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, "PILOT_LOCK")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConfigError("PILOT_BUSY", "Another pilot-control invocation holds the lock.") from None
            yield
        finally:
            os.close(fd)

    def _save(self, path, data):
        fd, temporary = tempfile.mkstemp(prefix=".lease-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _identity(self):
        _private_directory(self.target)
        # Lima's config and VZ identity are host-owned, never guest-provided.
        digests = []
        for name in ("lima.yaml", "vz-identifier"):
            fd = os.open(self.target / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
                        and not (info.st_mode & 0o022) and info.st_size <= 1048576, "PILOT_IDENTITY_FILE")
                data = stream.read(1048577)
                require(len(data) <= 1048576, "PILOT_IDENTITY_FILE")
                digests.append(hashlib.sha256(data).hexdigest())
        info = self.target.stat()
        return {"device": info.st_dev, "inode": info.st_ino, "config_sha256": digests[0], "vm_sha256": digests[1]}

    def _load(self):
        if not os.path.lexists(self.lease_path):
            return None
        lease = _decode(_read_private(self.lease_path))
        fields = {"schema_version", "lease_id", "instance", "lima_home", "identity", "boot_id",
                  "created_wall", "created_monotonic", "duration", "cancelled"}
        require(set(lease) == fields and type(lease["schema_version"]) is int and lease["schema_version"] == 1, "PILOT_LEASE_SCHEMA")
        require(lease["instance"] == self.name and lease["lima_home"] == str(self.home), "PILOT_LEASE_SCOPE")
        require(type(lease["lease_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", lease["lease_id"]), "PILOT_LEASE_SCHEMA")
        require(type(lease["boot_id"]) is str and re.fullmatch(r"[0-9a-f]{64}", lease["boot_id"]), "PILOT_LEASE_SCHEMA")
        require(type(lease["cancelled"]) is bool, "PILOT_LEASE_SCHEMA")
        require(type(lease["duration"]) is int and 1 <= lease["duration"] <= 3600, "PILOT_LEASE_SCHEMA")
        for field in ("created_wall", "created_monotonic"):
            require(type(lease[field]) in (float, int) and math.isfinite(lease[field]) and lease[field] >= 0, "PILOT_LEASE_SCHEMA")
        identity = lease["identity"]
        require(type(identity) is dict and set(identity) == {"device", "inode", "config_sha256", "vm_sha256"}, "PILOT_LEASE_SCHEMA")
        require(all(type(identity[f]) is int and identity[f] >= 0 for f in ("device", "inode")), "PILOT_LEASE_SCHEMA")
        require(all(type(identity[f]) is str and re.fullmatch(r"[0-9a-f]{64}", identity[f]) for f in ("config_sha256", "vm_sha256")), "PILOT_LEASE_SCHEMA")
        return lease

    def arm(self):
        with self._locked():
            require(self._load() is None, "PILOT_LEASE_EXISTS")
            require(self.driver.status(self.name) == "Stopped", "PILOT_MUST_BE_STOPPED")
            lease = {"schema_version": 1, "lease_id": uuid.uuid4().hex,
                     "instance": self.name, "lima_home": str(self.home), "identity": self._identity(),
                     "boot_id": self.get_boot_id(), "created_wall": self.clock.time(),
                     "created_monotonic": self.clock.monotonic(), "duration": self.duration, "cancelled": False}
            self._save(self.lease_path, lease)
            return {"ok": True, "action": "armed", "lease_id": lease["lease_id"], "lease_seconds": self.duration}

    def cancel(self):
        with self._locked():
            lease = self._load()
            require(lease is not None, "PILOT_NO_LEASE")
            lease["cancelled"] = True
            self._save(self.lease_path, lease)
            return {"ok": True, "action": "cancelled", "lease_id": lease["lease_id"]}

    def _reason(self, lease):
        if lease["cancelled"]:
            return "cancelled"
        if self.get_boot_id() != lease["boot_id"]:
            return "host_reboot"
        wall, monotonic = self.clock.time(), self.clock.monotonic()
        if wall < lease["created_wall"] or monotonic < lease["created_monotonic"]:
            return "clock_rollback"
        if wall >= lease["created_wall"] + lease["duration"] or monotonic >= lease["created_monotonic"] + lease["duration"]:
            return "expired"
        return "active"

    def _assert_identity(self, lease):
        require(self._identity() == lease["identity"], "PILOT_IDENTITY_CHANGED")

    def reap(self, *, apply=False):
        with self._locked():
            lease = self._load()
            if lease is None:
                return {"ok": True, "action": "no_lease"}
            reason = self._reason(lease)
            result = {"ok": True, "action": "keep" if reason == "active" else "would_delete",
                      "reason": reason, "lease_id": lease["lease_id"]}
            if reason == "active":
                return result
            status = self.driver.status(self.name)
            if status is None:
                require(not os.path.lexists(self.target), "PILOT_UNLISTED_STATE")
                result["action"] = "would_clear_absent_lease"
            else:
                require(status in ("Running", "Stopped"), "PILOT_UNKNOWN_STATUS")
                self._assert_identity(lease)
            if not apply:
                return result
            if status == "Running":
                try:
                    self.driver.stop(self.name)
                except ConfigError:
                    self._assert_identity(lease)
                    self.driver.stop(self.name, force=True)
                require(self.driver.status(self.name) == "Stopped", "PILOT_STOP_UNCONFIRMED")
            if status is not None:
                self._assert_identity(lease)
                self.driver.delete(self.name)
                require(self.driver.status(self.name) is None and not os.path.lexists(self.target), "PILOT_DELETE_UNCONFIRMED")
            result["action"] = "deleted" if status is not None else "cleared_absent_lease"
            self._save(self.directory / "last-cleanup.json", result)
            self.lease_path.unlink()
            self._sync_directory()
            return result
