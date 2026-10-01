import json
from pathlib import Path
import tempfile
import unittest

from runner_kit import ConfigError, Configuration, initialize
from runner_kit.lima import render_pilot


class PilotExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".local/config.json"
        initialize(self.path)

    def edit(self, change):
        data = json.loads(self.path.read_text())
        change(data)
        self.path.write_text(json.dumps(data))

    def test_export_excludes_central_credentials_and_host_integrations(self):
        self.edit(lambda d: d["secrets"]["values"].update(github_readonly_token="FAKE_EXPORT_CANARY"))
        profile = render_pilot(Configuration.load(self.path))
        self.assertNotIn("FAKE_EXPORT_CANARY", json.dumps(profile))
        self.assertTrue(profile["plain"])
        self.assertEqual(profile["mounts"], [])
        self.assertEqual(profile["provision"], [])
        self.assertFalse(profile["ssh"]["loadDotSSHPubKeys"])
        self.assertFalse(profile["propagateProxyEnv"])

    def test_one_config_change_updates_exported_allocation(self):
        self.edit(lambda d: d["settings"]["pilot_vm"].update(cpus=3, memory_mib=4096))
        profile = render_pilot(Configuration.load(self.path))
        self.assertEqual((profile["cpus"], profile["memory"]), (3, "4096MiB"))

    def test_refuses_unpinned_or_credential_bearing_images(self):
        for field, value in (("image_digest", "latest"), ("image_url", "https://user:FAKE_URL_CANARY@cloud-images.ubuntu.com/a.img")):
            with self.subTest(field=field):
                initialize_path = self.path
                original = initialize_path.read_text()
                self.edit(lambda d: d["settings"]["pilot_vm"].update({field: value}))
                with self.assertRaises(ConfigError) as result:
                    render_pilot(Configuration.load(self.path))
                self.assertEqual(result.exception.code, "VM_IMAGE")
                self.assertNotIn("FAKE_URL_CANARY", str(result.exception))
                initialize_path.write_text(original)

    def test_refuses_boolean_and_excessive_cpu_allocation(self):
        for value in (True, 0, 99):
            self.edit(lambda d: d["settings"]["pilot_vm"].update(cpus=value))
            with self.assertRaises(ConfigError) as result:
                render_pilot(Configuration.load(self.path))
            self.assertEqual(result.exception.code, "VM_RESOURCE")

    def test_unknown_mount_override_cannot_be_exported(self):
        self.edit(lambda d: d["settings"]["pilot_vm"].update(mounts=["/private"]))
        with self.assertRaises(ConfigError) as result:
            render_pilot(Configuration.load(self.path))
        self.assertEqual(result.exception.code, "VM_SCHEMA")
