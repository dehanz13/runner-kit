import json
from pathlib import Path
import tempfile
import unittest
from runner_kit import Configuration, ConfigError, initialize
from runner_kit.frontend import render_scope


class FrontendExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".local/config.json"
        initialize(self.path)
        self.data = json.loads(self.path.read_text())
        self.policy = {"schema_version": 1, "tests_ignore_prefixes": ["manual/"],
                       "code_extensions": [".ts"], "code_prefixes": ["assets/"], "workflow_prefixes": [".github/"]}
        self.data["settings"]["frontend_scope"] = self.policy
        self.data["components"]["frontend-config"] = {"trust": "trusted-service", "settings": ["frontend_scope"],
                                                     "environment": {}, "secret_environment": {}}

    def export(self):
        self.path.write_text(json.dumps(self.data))
        return render_scope(Configuration.load(self.path))

    def test_export_selects_only_the_customer_policy(self):
        self.data["secrets"]["values"]["github_readonly_token"] = "FAKE_NEVER_EXPORT_CANARY"
        self.assertEqual(self.export(), self.policy)
        self.assertNotIn("FAKE_NEVER_EXPORT_CANARY", json.dumps(self.export()))

    def test_private_setting_change_updates_the_generated_policy(self):
        self.policy["code_extensions"].append(".vue")
        self.assertEqual(self.export()["code_extensions"], [".ts", ".vue"])

    def test_invalid_paths_and_unknown_fields_refuse_export(self):
        self.policy["code_prefixes"] = ["../"]
        with self.assertRaises(ConfigError):
            self.export()
        self.policy["code_prefixes"] = ["assets/"]
        self.policy["extra"] = "FAKE_EXTRA_CANARY"
        with self.assertRaises(ConfigError) as error:
            self.export()
        self.assertNotIn("FAKE_EXTRA_CANARY", str(error.exception))
