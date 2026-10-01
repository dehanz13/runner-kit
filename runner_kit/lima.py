"""Render a mount-free pilot definition; never provision or register a runner."""

import re
from urllib.parse import urlsplit

from .config import ConfigError, Configuration


def render_pilot(config: Configuration) -> dict:
    """Export only reviewed VM fields, never arbitrary config or credentials.

    Plain mode removes host integrations. It does not enforce network isolation;
    this profile is for trusted lifecycle probes until external egress controls
    and disposable-state supervision have been implemented and verified.
    """
    settings = config.settings_for("vm-pilot").get("pilot_vm")
    fields = {"vm_type", "arch", "cpus", "memory_mib", "disk_gib", "image_url", "image_digest"}
    if not isinstance(settings, dict) or set(settings) != fields:
        raise ConfigError("VM_SCHEMA", "Pilot settings do not match the supported fields.")
    if settings["vm_type"] not in ("vz", "qemu") or settings["arch"] not in ("x86_64", "aarch64"):
        raise ConfigError("VM_PLATFORM", "Unsupported pilot hypervisor or architecture.")
    for name, low, high in (("cpus", 1, 4), ("memory_mib", 1024, 16384), ("disk_gib", 8, 64)):
        value = settings[name]
        if type(value) is not int or not low <= value <= high:
            raise ConfigError("VM_RESOURCE", "Pilot resource allocation is outside the supported bounds.")
    location, digest = settings["image_url"], settings["image_digest"]
    if not isinstance(location, str) or not isinstance(digest, str):
        raise ConfigError("VM_IMAGE", "Image must specify a URL and SHA-256 digest.")
    try:
        url = urlsplit(location)
        valid_url = (url.scheme == "https" and url.hostname == "cloud-images.ubuntu.com"
                     and url.port in (None, 443) and not url.username and not url.password
                     and not url.query and not url.fragment
                     and re.fullmatch(r"/[A-Za-z0-9/_\-.]+\.img", url.path))
    except ValueError:
        valid_url = False
    if not valid_url or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ConfigError("VM_IMAGE", "Pilot requires an approved HTTPS image and SHA-256 pin.")
    return {
        "minimumLimaVersion": "2.2.0",
        "vmType": settings["vm_type"], "arch": settings["arch"],
        "cpus": settings["cpus"], "memory": f'{settings["memory_mib"]}MiB',
        "disk": f'{settings["disk_gib"]}GiB',
        "images": [{"location": location, "arch": settings["arch"], "digest": digest}],
        "plain": True, "mounts": [], "portForwards": [],
        "containerd": {"system": False, "user": False},
        "ssh": {"loadDotSSHPubKeys": False, "forwardAgent": False},
        "propagateProxyEnv": False, "env": {}, "provision": [],
    }
