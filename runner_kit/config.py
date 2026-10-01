"""Private configuration and explicitly scoped environment construction.

No shell evaluation, ambient credential inheritance, network access or secret logging.
The config is trusted administrator input, not an authorization boundary against
another process running as the same operating-system user.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import stat
from collections.abc import Mapping, Iterator

MAX_BYTES = 1_048_576
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
SENSITIVE_KEY = re.compile(r"(^|_)(password|secret|credential|api_key|private_key|access_token|refresh_token)($|_)")
RESERVED_ENV = {"PATH", "HOME", "USER", "LOGNAME", "PWD", "SHELL", "ENV", "BASH_ENV", "SHELLOPTS", "NODE_OPTIONS", "RUNNER_KIT_CONFIG"}


class ConfigError(ValueError):
    """Safe-to-display diagnostic; never includes an input value or parser payload."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ConfigError(code, message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_KEY", "Configuration contains a duplicate key.")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ConfigError("INVALID_NUMBER", "Configuration contains a non-finite number.")


def _decode(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
    except ConfigError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ConfigError("INVALID_JSON", "Configuration must be bounded UTF-8 JSON.") from None
    _require(type(data) is dict, "INVALID_SCHEMA", "Configuration must be an object.")
    return data


def _private_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise ConfigError("PRIVATE_DIRECTORY", "Private config directory is unavailable.") from None
    _require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "PRIVATE_DIRECTORY", "Config parent must be a real directory.")
    _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
             "PRIVATE_DIRECTORY", "Config directory must be owned by this user with mode 0700.")


def _read_private(path: Path) -> bytes:
    _require(os.name == "posix", "UNSUPPORTED_PLATFORM", "Private-file validation currently supports macOS and Linux.")
    _private_directory(path.parent)
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                 "PRIVATE_FILE", "Config must be a regular file without additional hard links.")
        _require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) in (0o400, 0o600),
                 "PRIVATE_FILE", "Config must be owned by this user with mode 0400 or 0600.")
        _require(info.st_size <= MAX_BYTES, "CONFIG_SIZE", "Config exceeds the size limit.")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, "CONFIG_SIZE", "Config exceeds the size limit.")
        return raw
    except ConfigError:
        raise
    except OSError:
        raise ConfigError("CONFIG_READ", "Cannot safely read the private configuration file.") from None
    finally:
        if fd is not None:
            os.close(fd)


def _keys(data: dict, expected: set[str]) -> None:
    _require(type(data) is dict and set(data) == expected, "INVALID_SCHEMA", "Configuration fields do not match the supported schema.")


def _settings_tree(value, depth=0):
    _require(depth <= 6, "INVALID_SETTING", "Settings nesting exceeds the supported depth.")
    if type(value) is dict:
        _require(len(value) <= 128, "INVALID_SETTING", "Settings object exceeds the field limit.")
        for key, child in value.items():
            _require(bool(NAME.fullmatch(key)), "INVALID_SETTING", "Setting names must use lowercase identifiers.")
            _require(not SENSITIVE_KEY.search(key), "SECRET_IN_SETTINGS", "Credential settings belong in the secrets section.")
            _settings_tree(child, depth + 1)
    elif type(value) is list:
        _require(len(value) <= 128, "INVALID_SETTING", "Setting list exceeds the item limit.")
        for child in value:
            _settings_tree(child, depth + 1)
    else:
        _require(type(value) in (str, int, float, bool) or value is None, "INVALID_SETTING", "Unsupported setting value.")
        if type(value) is str:
            _require(len(value) <= 8192 and "\0" not in value, "INVALID_SETTING", "Setting string is too large or invalid.")
        if type(value) is float:
            _require(math.isfinite(value), "INVALID_NUMBER", "Setting must be finite.")


def _lookup(settings: dict, reference: str):
    _require(type(reference) is str and 0 < len(reference) <= 256, "SETTING_REFERENCE", "Invalid setting reference.")
    value = settings
    for part in reference.split("."):
        _require(bool(NAME.fullmatch(part)) and type(value) is dict and part in value,
                 "SETTING_REFERENCE", "Referenced setting does not exist.")
        value = value[part]
    return value


def _environment_name(name: str):
    _require(bool(ENV_NAME.fullmatch(name)), "ENVIRONMENT_NAME", "Invalid environment variable name.")
    _require(name not in RESERVED_ENV and not name.startswith(("LD_", "DYLD_", "PYTHON", "GIT_CONFIG")),
             "RESERVED_ENVIRONMENT", "Execution-control environment variables cannot be configured here.")


def _expanded(value, workspace: Path):
    if type(value) is str:
        result = value.replace("${workspace}", str(workspace))
        _require("${" not in result, "UNKNOWN_TEMPLATE", "Only the workspace placeholder is supported.")
        return result
    if type(value) is dict:
        return {key: _expanded(child, workspace) for key, child in value.items()}
    if type(value) is list:
        return [_expanded(child, workspace) for child in value]
    return value


class ComponentEnvironment(Mapping):
    """Read-only mapping; repr is safe, but values are sensitive once consumed."""

    def __init__(self, values: dict[str, str]):
        self.__values = dict(values)

    def __getitem__(self, key: str) -> str:
        return self.__values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__values)

    def __len__(self) -> int:
        return len(self.__values)

    def __repr__(self) -> str:
        return f"ComponentEnvironment({len(self)} variables; values hidden)"


class Configuration:
    """Immutable config snapshot with a small caller interface.

    Load again for a fresh invocation. Existing snapshots are unchanged; live
    service reload/watch behavior is deliberately not provided by this module.
    """

    def __init__(self, data: dict, path: Path):
        _keys(data, {"schema_version", "workspace_root", "settings", "components", "secrets"})
        _require(type(data["schema_version"]) is int and data["schema_version"] == 1,
                 "SCHEMA_VERSION", "Only configuration schema version 1 is supported.")
        workspace = data["workspace_root"]
        _require(type(workspace) is str and workspace and "\0" not in workspace,
                 "WORKSPACE_ROOT", "Workspace root must be a path string.")
        workspace_path = Path(workspace).expanduser()
        if not workspace_path.is_absolute():
            workspace_path = path.parent / workspace_path
        self.__workspace = workspace_path.resolve()
        _require(type(data["settings"]) is dict, "INVALID_SETTING", "Settings must be an object.")
        _settings_tree(data["settings"])
        self.__settings = _expanded(copy.deepcopy(data["settings"]), self.__workspace)
        secrets = data["secrets"]
        _keys(secrets, {"provider", "values"})
        _require(secrets["provider"] == "local", "SECRET_PROVIDER", "Only the explicitly selected local provider is implemented.")
        _require(type(secrets["values"]) is dict, "SECRET_SCHEMA", "Secret values must be an object.")
        for name, value in secrets["values"].items():
            _require(bool(NAME.fullmatch(name)), "SECRET_SCHEMA", "Invalid secret identifier.")
            _require(type(value) is str and len(value) <= 65536 and "\0" not in value,
                     "SECRET_SCHEMA", "Secret value must be a bounded string without NUL bytes.")
        self.__secrets = dict(secrets["values"])
        components = data["components"]
        _require(type(components) is dict and 0 < len(components) <= 64,
                 "COMPONENT_SCHEMA", "Configuration must define 1 to 64 components.")
        for name, component in components.items():
            _require(bool(NAME.fullmatch(name)), "COMPONENT_SCHEMA", "Invalid component identifier.")
            _keys(component, {"trust", "settings", "environment", "secret_environment"})
            _require(component["trust"] in ("trusted-service", "isolated-job"), "COMPONENT_TRUST", "Invalid component trust class.")
            sections = component["settings"]
            _require(type(sections) is list and all(type(s) is str for s in sections) and len(set(sections)) == len(sections),
                     "COMPONENT_SCHEMA", "Settings selection must be a list of unique section names.")
            _require(all(s in self.__settings for s in sections), "SETTING_REFERENCE", "Selected settings section does not exist.")
            env, secret_env = component["environment"], component["secret_environment"]
            _require(type(env) is dict and type(secret_env) is dict, "COMPONENT_SCHEMA", "Environment bindings must be objects.")
            _require(not (set(env) & set(secret_env)), "ENVIRONMENT_COLLISION", "An environment variable cannot have two sources.")
            _require(component["trust"] != "isolated-job" or not secret_env,
                     "ISOLATED_SECRET", "Isolated jobs cannot receive central secrets.")
            for env_name, reference in env.items():
                _environment_name(env_name)
                _require(not re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL|PRIVATE_KEY|API_KEY", env_name),
                         "SECRET_IN_SETTINGS", "Credential environment bindings must use the secret section.")
                value = _lookup(self.__settings, reference)
                _require(reference.split(".")[0] in sections, "SETTING_SCOPE", "Environment reference is outside the component's selected settings.")
                _require(type(value) in (str, int, float, bool), "ENVIRONMENT_VALUE", "Environment bindings must reference scalar settings.")
            for env_name, secret_name in secret_env.items():
                _environment_name(env_name)
                _require(type(secret_name) is str and secret_name in self.__secrets,
                         "SECRET_REFERENCE", "Referenced secret slot does not exist.")
        self.__components = copy.deepcopy(components)

    @classmethod
    def load(cls, path: str | Path) -> Configuration:
        target = Path(path).expanduser().absolute()
        return cls(_decode(_read_private(target)), target)

    def _component(self, component: str) -> dict:
        _require(component in self.__components, "UNKNOWN_COMPONENT", "The requested component is not configured.")
        return self.__components[component]

    def settings_for(self, component: str) -> dict:
        selected = self._component(component)["settings"]
        return copy.deepcopy({name: self.__settings[name] for name in selected})

    def environment_for(self, component: str) -> ComponentEnvironment:
        selected = self._component(component)
        values = {}
        for name, reference in selected["environment"].items():
            value = _lookup(self.__settings, reference)
            values[name] = str(value).lower() if type(value) is bool else str(value)
        for name, reference in selected["secret_environment"].items():
            secret = self.__secrets[reference]
            _require(bool(secret), "SECRET_UNSET", "A secret required by this component has not been configured.")
            values[name] = secret
        return ComponentEnvironment(values)

    def summary(self) -> dict:
        return {
            "schema_version": 1,
            "secret_provider": "local",
            "secret_slots": len(self.__secrets),
            "unset_secret_slots": sum(not value for value in self.__secrets.values()),
            "components": {
                name: {"trust": item["trust"], "environment_names": sorted([*item["environment"], *item["secret_environment"]])}
                for name, item in self.__components.items()
            },
        }

    def __repr__(self) -> str:
        return "Configuration(private values hidden)"


def initialize(path: str | Path, workspace: str | Path | None = None) -> None:
    """Create one empty-secret private config. Never overwrite or chmod an existing file."""
    target = Path(path).expanduser().absolute()
    _require(os.name == "posix", "UNSUPPORTED_PLATFORM", "Initialization currently supports macOS and Linux.")
    if not target.parent.exists():
        try:
            target.parent.mkdir(mode=0o700, parents=True)
        except OSError:
            raise ConfigError("PRIVATE_DIRECTORY", "Cannot create the private config directory.") from None
    _private_directory(target.parent)
    template = _decode(Path(__file__).with_name("defaults.json").read_bytes())
    template["workspace_root"] = str(Path(workspace).expanduser().resolve()) if workspace else ".."
    Configuration(template, target)
    payload = (json.dumps(template, indent=2) + "\n").encode()
    fd = None
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise ConfigError("CONFIG_EXISTS", "Config already exists; initialization never overwrites it.") from None
    except OSError:
        raise ConfigError("CONFIG_WRITE", "Cannot create the private configuration file.") from None
    finally:
        if fd is not None:
            os.close(fd)
