#!/usr/bin/env python3
"""Tests for container/ensure_proxy_config.py.

Plain `assert`s, so this is a real test suite under `pytest tests/` (which is
what the release pipeline runs) and still works as `python tests/test_proxy_config.py`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "..", "container", "ensure_proxy_config.py")

_spec = importlib.util.spec_from_file_location("ensure_proxy_config", MODULE_PATH)
epc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(epc)

MONOLITH_CONFIG = """# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
    - ::1
    - 172.18.0.0/16
"""


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates HA's !include / !secret tags."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def parsed(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_Loader)


def write(tmp: str, text: str | None) -> str:
    path = os.path.join(tmp, "configuration.yaml")
    if text is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path


def test_migrated_config_gains_private_ranges_and_keeps_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, MONOLITH_CONFIG)
        assert epc.ensure(tmp) is True
        http = parsed(path)["http"]
        assert http["use_x_forwarded_for"] is True
        # The monolith's own subnet must not be thrown away.
        assert "172.18.0.0/16" in http["trusted_proxies"]
        for cidr in epc.REQUIRED_PROXIES:
            assert cidr in http["trusted_proxies"], cidr
        # Nothing outside the http block is touched.
        assert "!include_dir_merge_named themes" in open(path, encoding="utf-8").read()


def test_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, MONOLITH_CONFIG)
        epc.ensure(tmp)
        assert epc.ensure(tmp) is False


def test_fresh_volume_gets_a_full_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, None)
        assert epc.ensure(tmp) is True
        assert parsed(path)["http"]["use_x_forwarded_for"] is True
        assert "default_config:" in open(path, encoding="utf-8").read()


def test_config_without_an_http_block():
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "default_config:\n\nautomation: !include automations.yaml\n")
        assert epc.ensure(tmp) is True
        assert parsed(path)["http"]["use_x_forwarded_for"] is True
        assert "automation: !include automations.yaml" in open(path, encoding="utf-8").read()


def test_unrelated_http_keys_survive():
    """Silently losing someone's TLS config while fixing a proxy setting would
    be a worse failure than the 400 this script exists to prevent."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "http:\n"
                          "  server_port: 8123\n"
                          "  ssl_certificate: /ssl/fullchain.pem\n"
                          "  trusted_proxies:\n"
                          "    - 127.0.0.1\n")
        epc.ensure(tmp)
        http = parsed(path)["http"]
        assert http["use_x_forwarded_for"] is True
        assert http["server_port"] == 8123
        assert http["ssl_certificate"] == "/ssl/fullchain.pem"
        assert "127.0.0.1" in http["trusted_proxies"]


def test_repeat_rewrites_do_not_accumulate():
    """The entrypoint runs on every boot; nothing may grow file-over-file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "http:\n  server_port: 8123\n")
        epc.ensure(tmp)
        first = open(path, encoding="utf-8").read()
        # Force a second rewrite by dropping a required range back out.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(first.replace("    - 192.168.0.0/16\n", ""))
        assert epc.ensure(tmp) is True
        second = open(path, encoding="utf-8").read()
        assert second.count("# Managed by aw-app-home-assistant") == 1
        assert second.count("server_port") == 1
        assert parsed(path)["http"]["server_port"] == 8123


def test_a_disabled_use_x_forwarded_for_is_corrected():
    """`false` is as broken as missing — HA still 400s."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "http:\n  use_x_forwarded_for: false\n")
        assert epc.ensure(tmp) is True
        assert parsed(path)["http"]["use_x_forwarded_for"] is True


# --- .storage/http (modern HA, where the running server actually reads) -----

STORED = {
    "version": 2, "minor_version": 2, "key": "http",
    "data": {
        "stable": {
            "use_x_forwarded_for": True,
            "trusted_proxies": ["127.0.0.1/32", "::1/128", "172.18.0.0/16"],
            "server_port": 8123, "error": None, "error_message": None,
        },
        "pending": {
            "use_x_forwarded_for": True,
            "trusted_proxies": ["127.0.0.1/32", "10.0.0.0/8"],
            "error": "not_promoted", "error_message": None,
        },
        "yaml_migration_done": True,
    },
}


def write_stored(tmp, doc=None):
    import copy
    os.makedirs(os.path.join(tmp, ".storage"), exist_ok=True)
    path = os.path.join(tmp, ".storage", "http")
    with open(path, "w") as f:
        json.dump(copy.deepcopy(doc if doc is not None else STORED), f)
    return path


def read_stored(tmp):
    with open(os.path.join(tmp, ".storage", "http")) as f:
        return json.load(f)


def test_no_storage_file_means_this_ha_is_yaml_only():
    with tempfile.TemporaryDirectory() as tmp:
        assert epc.ensure_storage(tmp) is None


def test_stable_gains_the_private_ranges_and_keeps_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        write_stored(tmp)
        assert epc.ensure_storage(tmp) is True
        stable = read_stored(tmp)["data"]["stable"]
        assert stable["use_x_forwarded_for"] is True
        assert "172.18.0.0/16" in stable["trusted_proxies"]
        for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            assert cidr in stable["trusted_proxies"], cidr
        # Unrelated stored settings survive.
        assert stable["server_port"] == 8123


def test_a_failed_pending_trial_is_dropped():
    """`not_promoted` is skipped forever and only misleads whoever reads next."""
    with tempfile.TemporaryDirectory() as tmp:
        write_stored(tmp)
        epc.ensure_storage(tmp)
        assert read_stored(tmp)["data"]["pending"] is None


def test_storage_pass_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        write_stored(tmp)
        epc.ensure_storage(tmp)
        assert epc.ensure_storage(tmp) is False


def test_bare_ips_are_normalised_so_they_are_not_re_added_forever():
    """HA stores networks; a bare '10.0.0.0/8' vs '10.0.0.0/8' must compare equal."""
    import copy
    doc = copy.deepcopy(STORED)
    doc["data"]["stable"]["trusted_proxies"] = [
        "127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    doc["data"]["pending"] = None
    with tempfile.TemporaryDirectory() as tmp:
        write_stored(tmp, doc)
        assert epc.ensure_storage(tmp) is False


def test_our_yaml_block_is_removed_once_storage_owns_it():
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, MONOLITH_CONFIG)
        epc.ensure(tmp)                      # stamps our marker into the block
        assert epc.strip_managed_yaml_block(tmp) is True
        text = open(os.path.join(tmp, "configuration.yaml")).read()
        assert "http:" not in text
        assert "automation: !include automations.yaml" in text


def test_a_hand_written_yaml_block_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, "http:\n  server_port: 8123\n\ndefault_config:\n")
        assert epc.strip_managed_yaml_block(tmp) is False
        assert "server_port" in open(os.path.join(tmp, "configuration.yaml")).read()


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        getattr(mod, name)()
        print(f"  ok   {name}")
    print("all checks passed")
