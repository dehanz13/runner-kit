"""Safe config inspection: intentionally no command that prints secret values."""

import argparse
import json
import os

from .config import ConfigError, Configuration, initialize
from .lima import render_pilot
from .pilot_control import PilotControl
from .frontend import render_scope


def main(argv=None):
    parser = argparse.ArgumentParser(prog="runner-kit")
    parser.add_argument("--config", default=os.environ.get("RUNNER_KIT_CONFIG"), help="Private config path; alternatively RUNNER_KIT_CONFIG")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a private config with empty secret slots; never overwrite")
    init.add_argument("--workspace", help="Workspace root for dynamic paths")
    commands.add_parser("check", help="Validate private config without printing values")
    commands.add_parser("describe", help="List component trust and variable names, never values")
    commands.add_parser("render-lima", help="Export a nonsecret pilot VM definition; does not provision")
    commands.add_parser("render-frontend-scope", help="Export only the nonsecret frontend scope policy")
    commands.add_parser("pilot-arm", help="Adopt the configured stopped pilot for deadline-based cleanup")
    commands.add_parser("pilot-cancel", help="Mark the pilot lease cancelled; does not delete anything")
    reap = commands.add_parser("pilot-reap", help="Preview cleanup of an expired or cancelled owned pilot")
    reap.add_argument("--apply", action="store_true", help="Stop/delete only the exact leased pilot when due")
    args = parser.parse_args(argv)
    try:
        if not args.config:
            raise ConfigError("CONFIG_PATH", "Supply --config or RUNNER_KIT_CONFIG.")
        if args.command == "init":
            initialize(args.config, args.workspace)
            print(json.dumps({"ok": True, "created": True, "credentials_configured": False}))
        else:
            snapshot = Configuration.load(args.config)
            if args.command == "render-frontend-scope":
                print(json.dumps(render_scope(snapshot), indent=2))
                return 0
            if args.command.startswith("pilot-"):
                control = PilotControl(snapshot)
                if args.command == "pilot-arm":
                    result = control.arm()
                elif args.command == "pilot-cancel":
                    result = control.cancel()
                else:
                    result = control.reap(apply=args.apply)
                print(json.dumps(result, indent=2))
                return 0
            if args.command == "render-lima":
                print(json.dumps(render_pilot(snapshot), indent=2))
                return 0
            summary = snapshot.summary()
            if args.command == "check":
                summary["component_count"] = len(summary.pop("components"))
            print(json.dumps({"ok": True, **summary}, indent=2))
        return 0
    except ConfigError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": str(exc)}))
        return 2
    except OSError:
        print(json.dumps({"ok": False, "error": "LOCAL_OPERATION_FAILED", "message": "A local file or process operation failed; inspect private host state."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
