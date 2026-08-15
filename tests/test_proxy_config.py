#!/usr/bin/env python3
"""Tests for container/ensure_proxy_config.py.

Plain `assert`s, so this is a real test suite under `pytest tests/` (which is
what the release pipeline runs) and still works as `python tests/test_proxy_config.py`.
"""
from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    for name in [n for n in dir(mod) if n.startswith("test_")]:
        getattr(mod, name)()
        print(f"  ok   {name}")
    print("all checks passed")
