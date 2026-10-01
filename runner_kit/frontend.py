"""Export only a non-secret scope policy for a frontend customer."""
import re
from .config import ConfigError


def render_scope(config):
    policy = config.settings_for("frontend-config").get("frontend_scope")
    fields = {"schema_version", "tests_ignore_prefixes", "code_extensions", "code_prefixes", "workflow_prefixes"}
    valid = isinstance(policy, dict) and set(policy) == fields
    if valid:
        valid = type(policy["schema_version"]) is int and policy["schema_version"] == 1
    if valid:
        for field in fields - {"schema_version"}:
            values = policy[field]
            if not isinstance(values, list) or len(values) > 64 or not all(type(v) is str for v in values):
                valid = False
                break
            if len(set(values)) != len(values):
                valid = False
                break
            for value in values:
                pattern = r"\.[a-z0-9]+" if field == "code_extensions" else r"(?:[a-zA-Z0-9_.-]+/)+"
                if len(value) > 128 or not re.fullmatch(pattern, value) or any(p in (".", "..") for p in value.split("/")):
                    valid = False
    if not valid:
        raise ConfigError("FRONTEND_POLICY", "Frontend scope policy is invalid; no configuration was exported.")
    return policy
