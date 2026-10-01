import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runner_kit import ConfigError, Configuration, initialize
from runner_kit.cli import main


class PrivateConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / ".local/config.json"
        initialize(self.path, self.root)

    def edit(self, change):
        data = json.loads(self.path.read_text())
        change(data)
        self.path.write_text(json.dumps(data))

    def assert_invalid(self, code):
        with self.assertRaises(ConfigError) as result:
            Configuration.load(self.path)
        self.assertEqual(result.exception.code, code)

    def test_initialize_is_private_and_never_overwrites(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        original = self.path.read_bytes()
        with self.assertRaises(ConfigError) as result:
            initialize(self.path, self.root)
        self.assertEqual(result.exception.code, "CONFIG_EXISTS")
        self.assertEqual(self.path.read_bytes(), original)

    def test_one_setting_update_reaches_all_bound_components_on_reload(self):
        first = Configuration.load(self.path)
        self.assertEqual(first.environment_for("ci-worker")["RK_VCPUS"], "4")
        self.edit(lambda data: data["settings"]["runner"].update(vcpus=6))
        second = Configuration.load(self.path)
        self.assertEqual(second.environment_for("ci-worker")["RK_VCPUS"], "6")
        self.assertEqual(second.settings_for("runner-supervisor")["runner"]["vcpus"], 6)
        self.assertEqual(first.environment_for("ci-worker")["RK_VCPUS"], "4")

    def test_settings_return_copies_and_expand_only_workspace(self):
        config = Configuration.load(self.path)
        settings = config.settings_for("archive-worker")
        self.assertEqual(settings["paths"]["archive"], str(self.root / ".archive"))
        settings["archive"]["monthly_cloud_budget_usd"] = 999
        self.assertEqual(config.settings_for("archive-worker")["archive"]["monthly_cloud_budget_usd"], 4)

    def test_each_user_file_has_independent_credentials(self):
        self.edit(lambda data: data["secrets"]["values"].update(github_readonly_token="FAKE_FIRST_USER_CANARY"))
        other = self.root / "other-private/config.json"
        initialize(other, self.root)
        second_data = json.loads(other.read_text())
        second_data["secrets"]["values"]["github_readonly_token"] = "FAKE_SECOND_USER_CANARY"
        other.write_text(json.dumps(second_data))
        first = Configuration.load(self.path).environment_for("dashboard-reader")
        second = Configuration.load(other).environment_for("dashboard-reader")
        self.assertEqual(first["GH_TOKEN"], "FAKE_FIRST_USER_CANARY")
        self.assertEqual(second["GH_TOKEN"], "FAKE_SECOND_USER_CANARY")
        self.assertNotIn("FAKE_FIRST_USER_CANARY", repr(first))

    def test_environment_does_not_inherit_ambient_credentials(self):
        with contextlib.ExitStack() as stack:
            from unittest.mock import patch
            stack.enter_context(patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "FAKE_AMBIENT_CANARY"}))
            env = Configuration.load(self.path).environment_for("ci-worker")
            self.assertEqual(dict(env), {"RK_VCPUS": "4", "RK_MEMORY_MIB": "12288", "RK_TIMEOUT_MINUTES": "45"})

    def test_missing_secret_only_blocks_component_that_needs_it(self):
        config = Configuration.load(self.path)
        self.assertEqual(config.environment_for("ci-worker")["RK_VCPUS"], "4")
        with self.assertRaises(ConfigError) as result:
            config.environment_for("dashboard-reader")
        self.assertEqual(result.exception.code, "SECRET_UNSET")

    def test_isolated_jobs_cannot_bind_central_secrets(self):
        self.edit(lambda data: data["components"]["ci-worker"]["secret_environment"].update(GH_TOKEN="github_readonly_token"))
        self.assert_invalid("ISOLATED_SECRET")

    def test_component_cannot_reference_unselected_settings(self):
        self.edit(lambda data: data["components"]["ci-worker"]["environment"].update(PORT="dashboard.port"))
        self.assert_invalid("SETTING_SCOPE")

    def test_permissions_are_rejected_without_repairing_them(self):
        self.path.chmod(0o644)
        self.assert_invalid("PRIVATE_FILE")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.path.chmod(0o600)
        self.path.parent.chmod(0o755)
        self.assert_invalid("PRIVATE_DIRECTORY")

    def test_final_symlink_and_hardlink_are_rejected(self):
        real = self.path.with_name("original.json")
        self.path.rename(real)
        self.path.symlink_to(real)
        self.assert_invalid("CONFIG_READ")
        self.path.unlink()
        os.link(real, self.path)
        self.assert_invalid("PRIVATE_FILE")

    def test_symlink_parent_is_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ConfigError) as result:
            Configuration.load(alias / "config.json")
        self.assertEqual(result.exception.code, "PRIVATE_DIRECTORY")

    def test_duplicate_keys_and_nonfinite_values_fail_closed(self):
        self.path.write_text('{"schema_version": 1, "schema_version": 1}')
        self.assert_invalid("DUPLICATE_KEY")
        self.path.write_text('{"schema_version": NaN}')
        self.assert_invalid("INVALID_NUMBER")

    def test_parse_errors_and_summary_never_echo_canary_secrets(self):
        canary = "FAKE_SECRET_NEVER_PRINT_THIS"
        self.edit(lambda data: data["secrets"]["values"].update(github_readonly_token=canary))
        config = Configuration.load(self.path)
        self.assertNotIn(canary, json.dumps(config.summary()))
        self.assertNotIn(canary, repr(config))
        self.path.write_text('{"secrets": "' + canary + '" invalid}')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--config", str(self.path), "check"])
        self.assertEqual(code, 2)
        self.assertNotIn(canary, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["error"], "INVALID_JSON")

    def test_cli_describe_is_value_free(self):
        canary = "FAKE_CLI_SECRET_CANARY"
        self.edit(lambda data: data["secrets"]["values"].update(github_readonly_token=canary))
        result = subprocess.run([sys.executable, "-m", "runner_kit", "--config", str(self.path), "describe"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(canary, result.stdout + result.stderr)
        self.assertIn("GH_TOKEN", result.stdout)

    def test_shell_text_is_data_and_unknown_expansion_fails(self):
        marker = self.root / "must-not-exist"
        self.edit(lambda data: data["settings"]["paths"].update(archive=f'$(touch {marker})'))
        config = Configuration.load(self.path)
        self.assertEqual(config.settings_for("archive-worker")["paths"]["archive"], f'$(touch {marker})')
        self.assertFalse(marker.exists())
        self.edit(lambda data: data["settings"]["paths"].update(archive="${HOME}/archive"))
        self.assert_invalid("UNKNOWN_TEMPLATE")

    def test_reserved_execution_environment_cannot_be_injected(self):
        self.edit(lambda data: data["components"]["ci-worker"]["environment"].update(PYTHONPATH="runner.vcpus"))
        self.assert_invalid("RESERVED_ENVIRONMENT")

    def test_credentials_must_use_secret_bindings(self):
        self.edit(lambda data: data["components"]["dashboard-reader"]["environment"].update(API_KEY="dashboard.port"))
        self.assert_invalid("SECRET_IN_SETTINGS")

    def test_unknown_provider_is_rejected(self):
        self.edit(lambda data: data["secrets"].update(provider="imaginary-vault"))
        self.assert_invalid("SECRET_PROVIDER")

    def test_large_file_is_rejected(self):
        self.path.write_bytes(b" " * 1_048_577)
        self.assert_invalid("CONFIG_SIZE")

    def test_environment_collision_is_rejected(self):
        self.edit(lambda data: data["components"]["dashboard-reader"]["secret_environment"].update(PORT="github_readonly_token"))
        self.assert_invalid("ENVIRONMENT_COLLISION")

    def test_unknown_and_boolean_schema_versions_are_rejected(self):
        self.edit(lambda data: data.update(schema_version=2))
        self.assert_invalid("SCHEMA_VERSION")
        self.edit(lambda data: data.update(schema_version=True))
        self.assert_invalid("SCHEMA_VERSION")

    def test_non_utf8_config_is_rejected(self):
        self.path.write_bytes(self.path.read_text().encode("utf-16"))
        self.assert_invalid("INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
