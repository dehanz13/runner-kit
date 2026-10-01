import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from runner_kit import ConfigError, Configuration, initialize
from runner_kit.pilot_control import PilotControl


class Clock:
    def __init__(self):
        self.wall, self.mono = 10000, 1000

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono


class FakeLima:
    def __init__(self, target):
        self.target = target
        self.current = "Stopped"
        self.calls = []
        self.fail_stop = False
        self.fail_delete = False
        self.fail_list = False

    def status(self, name):
        if self.fail_list:
            raise ConfigError("TEST_LIST_FAILED", "synthetic failure")
        return self.current

    def stop(self, name, *, force=False):
        self.calls.append(("stop", name, force))
        if self.fail_stop and not force:
            raise ConfigError("TEST_STOP_FAILED", "synthetic failure")
        self.current = "Stopped"

    def delete(self, name):
        self.calls.append(("delete", name))
        if self.fail_delete:
            raise ConfigError("TEST_DELETE_FAILED", "synthetic failure")
        shutil.rmtree(self.target)
        self.current = None


class PilotControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.config_path = self.workspace / ".local/config.json"
        initialize(self.config_path, self.workspace)
        self.target = self.workspace / ".state/lima/rk-pilot"
        self.target.mkdir(parents=True, mode=0o700)
        self.target.parent.chmod(0o700)
        (self.target / "lima.yaml").write_text("plain: true\n")
        (self.target / "vz-identifier").write_bytes(b"synthetic VM identifier")
        (self.target / "lima.yaml").chmod(0o600)
        (self.target / "vz-identifier").chmod(0o600)
        self.clock = Clock()
        self.boot = "a" * 64
        self.driver = FakeLima(self.target)
        self.control = self.fresh()

    def fresh(self):
        return PilotControl(Configuration.load(self.config_path), driver=self.driver,
                            clock=self.clock, get_boot_id=lambda: self.boot)

    def expire(self):
        self.clock.mono += 901
        self.clock.wall += 901

    def test_durable_lease_survives_new_controller_without_renewal(self):
        self.control.arm()
        self.assertEqual(self.fresh().reap(apply=True)["action"], "keep")
        self.assertEqual(self.driver.calls, [])
        with self.assertRaises(ConfigError):
            self.fresh().arm()

    def test_preview_then_expiry_deletes_only_owned_instance(self):
        unrelated = self.target.parent / "unrelated-service"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("persistent data")
        self.control.arm()
        self.expire()
        self.assertEqual(self.fresh().reap()["action"], "would_delete")
        self.assertTrue(self.target.exists())
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.fresh().reap(apply=True)["action"], "deleted")
        self.assertEqual(self.driver.calls, [("delete", "rk-pilot")])
        self.assertTrue((unrelated / "keep.txt").exists())
        self.assertEqual(self.fresh().reap(apply=True)["action"], "no_lease")

    def test_cancellation_persists_and_running_vm_stops_before_delete(self):
        self.control.arm()
        self.driver.current = "Running"
        self.fresh().cancel()
        self.assertEqual(self.driver.calls, [])
        result = self.fresh().reap(apply=True)
        self.assertEqual(result["reason"], "cancelled")
        self.assertEqual(self.driver.calls, [("stop", "rk-pilot", False), ("delete", "rk-pilot")])

    def test_reboot_makes_old_lease_due(self):
        self.control.arm()
        self.boot = "b" * 64
        self.assertEqual(self.fresh().reap()["reason"], "host_reboot")

    def test_rollback_is_conservative_and_monotonic_expiry_still_works(self):
        self.control.arm()
        self.clock.wall -= 1
        self.assertEqual(self.control.reap()["reason"], "clock_rollback")
        self.clock.wall += 1
        self.clock.mono += 901
        self.assertEqual(self.control.reap()["reason"], "expired")

    def test_config_edit_cannot_extend_existing_lease(self):
        self.control.arm()
        data = json.loads(self.config_path.read_text())
        data["settings"]["pilot_control"]["lease_seconds"] = 3600
        self.config_path.write_text(json.dumps(data))
        self.expire()
        self.assertEqual(self.fresh().reap()["reason"], "expired")

    def test_changed_identity_refuses_deletion_and_retains_lease(self):
        self.control.arm()
        self.expire()
        (self.target / "vz-identifier").write_bytes(b"replacement VM")
        with self.assertRaises(ConfigError) as result:
            self.control.reap(apply=True)
        self.assertEqual(result.exception.code, "PILOT_IDENTITY_CHANGED")
        self.assertEqual(self.driver.calls, [])
        self.assertTrue(self.control.lease_path.exists())

    def test_group_writable_identity_is_rejected(self):
        (self.target / "lima.yaml").chmod(0o664)
        with self.assertRaises(ConfigError) as result:
            self.control.arm()
        self.assertEqual(result.exception.code, "PILOT_IDENTITY_FILE")
        self.assertFalse(self.control.lease_path.exists())

    def test_guest_name_cannot_become_a_path_or_option(self):
        for name in ("../existing-service", "--all", "existing-service", "rk-foo/../bar"):
            data = json.loads(self.config_path.read_text())
            data["settings"]["pilot_control"]["instance"] = name
            self.config_path.write_text(json.dumps(data))
            with self.assertRaises(ConfigError):
                self.fresh()

    def test_force_stop_is_scoped_and_only_after_graceful_failure(self):
        self.control.arm()
        self.driver.current, self.driver.fail_stop = "Running", True
        self.control.cancel()
        self.control.reap(apply=True)
        self.assertEqual(self.driver.calls, [("stop", "rk-pilot", False),
                                            ("stop", "rk-pilot", True), ("delete", "rk-pilot")])

    def test_delete_failure_retains_retry_obligation(self):
        self.control.arm()
        self.control.cancel()
        self.driver.fail_delete = True
        with self.assertRaises(ConfigError):
            self.control.reap(apply=True)
        self.assertTrue(self.control.lease_path.exists())
        self.driver.fail_delete = False
        self.assertEqual(self.fresh().reap(apply=True)["action"], "deleted")

    def test_inventory_error_is_not_absence(self):
        self.control.arm()
        self.expire()
        self.driver.fail_list = True
        with self.assertRaises(ConfigError):
            self.control.reap(apply=True)
        self.assertTrue(self.control.lease_path.exists())

    def test_crash_after_delete_reconciles_without_repeating_deletion(self):
        self.control.arm()
        self.expire()
        self.driver.delete("rk-pilot")
        self.driver.calls.clear()
        self.assertEqual(self.fresh().reap(apply=True)["action"], "cleared_absent_lease")
        self.assertEqual(self.driver.calls, [])

    def test_unknown_state_is_never_deleted(self):
        self.control.arm()
        self.expire()
        self.driver.current = "Broken"
        with self.assertRaises(ConfigError):
            self.control.reap(apply=True)
        self.assertEqual(self.driver.calls, [])

    def test_unleased_running_or_absent_vm_is_not_adopted(self):
        for status in ("Running", None):
            self.driver.current = status
            with self.assertRaises(ConfigError):
                self.control.arm()
        self.assertEqual(self.control.reap(apply=True)["action"], "no_lease")

    def test_parallel_controller_is_refused(self):
        self.control.arm()
        with (self.control.directory / "lock").open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ConfigError) as result:
                self.fresh().cancel()
        self.assertEqual(result.exception.code, "PILOT_BUSY")

    def test_lease_symlink_is_not_followed(self):
        self.control.arm()
        outside = self.workspace / "outside.json"
        self.control.lease_path.rename(outside)
        self.control.lease_path.symlink_to(outside)
        with self.assertRaises(ConfigError):
            self.control.cancel()
        self.assertFalse(json.loads(outside.read_text())["cancelled"])

    def test_malformed_lease_fails_closed(self):
        self.control.arm()
        data = json.loads(self.control.lease_path.read_text())
        data["duration"] = True
        self.control.lease_path.write_text(json.dumps(data))
        with self.assertRaises(ConfigError):
            self.control.reap(apply=True)
        self.assertEqual(self.driver.calls, [])


if __name__ == "__main__":
    unittest.main()
