#!/usr/bin/env python3
"""Tests for container/ensure_proxy_config.py.

Runnable with plain `python tests/test_proxy_config.py` (no pytest needed) so
it works inside the HA image too, which has no dev dependencies.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

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

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


def parsed_http(path: str) -> dict:
    """Load the file with HA's custom tags stubbed out, return the http block."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader)["http"]


def write(tmp: str, text: str | None) -> str:
    path = os.path.join(tmp, "configuration.yaml")
    if text is not None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path


def test_migrated_config_gains_private_ranges_and_keeps_its_own():
    print("migrated monolith config")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, MONOLITH_CONFIG)
        check("reports a change", epc.ensure(tmp) is True)
        http = parsed_http(path)
        check("use_x_forwarded_for stays on", http["use_x_forwarded_for"] is True)
        check("keeps the pre-existing 172.18.0.0/16",
              "172.18.0.0/16" in http["trusted_proxies"])
        for cidr in epc.REQUIRED_PROXIES:
            check(f"adds {cidr}", cidr in http["trusted_proxies"])
        check("leaves the rest of the file alone",
              "!include_dir_merge_named themes" in open(path, encoding="utf-8").read())


def test_is_idempotent():
    print("idempotence")
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, MONOLITH_CONFIG)
        epc.ensure(tmp)
        check("second pass is a no-op", epc.ensure(tmp) is False)


def test_fresh_volume_gets_a_full_config():
    print("fresh volume (no configuration.yaml)")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, None)
        check("reports a change", epc.ensure(tmp) is True)
        http = parsed_http(path)
        check("use_x_forwarded_for set", http["use_x_forwarded_for"] is True)
        check("default_config present",
              "default_config:" in open(path, encoding="utf-8").read())


def test_config_without_an_http_block():
    print("config with no http: block")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "default_config:\n\nautomation: !include automations.yaml\n")
        check("reports a change", epc.ensure(tmp) is True)
        http = parsed_http(path)
        check("http block appended", http["use_x_forwarded_for"] is True)
        check("original keys survive",
              "automation: !include automations.yaml"
              in open(path, encoding="utf-8").read())


def test_http_block_with_other_keys_is_not_silently_dropped():
    """A user's own http keys (server_port, ssl_certificate…) must not vanish."""
    print("http: block carrying unrelated keys")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "http:\n"
                          "  server_port: 8123\n"
                          "  ssl_certificate: /ssl/fullchain.pem\n"
                          "  trusted_proxies:\n"
                          "    - 127.0.0.1\n")
        epc.ensure(tmp)
        http = parsed_http(path)
        check("proxy keys are correct", http["use_x_forwarded_for"] is True)
        check("server_port survives", http.get("server_port") == 8123)
        check("ssl_certificate survives",
              http.get("ssl_certificate") == "/ssl/fullchain.pem")
        check("original proxy survives", "127.0.0.1" in http["trusted_proxies"])


def test_repeat_runs_do_not_accumulate_comments():
    """The managed marker comment must not be re-added on every boot."""
    print("no comment accumulation across runs")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "http:\n  server_port: 8123\n")
        epc.ensure(tmp)
        first = open(path, encoding="utf-8").read()
        # Force a second rewrite by removing a required range.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(first.replace("    - 192.168.0.0/16\n", ""))
        epc.ensure(tmp)
        second = open(path, encoding="utf-8").read()
        check("marker comment appears exactly once",
              second.count("# Managed by aw-app-home-assistant") == 1)
        check("server_port still there once", second.count("server_port") == 1)


if __name__ == "__main__":
    test_migrated_config_gains_private_ranges_and_keeps_its_own()
    test_is_idempotent()
    test_fresh_volume_gets_a_full_config()
    test_config_without_an_http_block()
    test_http_block_with_other_keys_is_not_silently_dropped()
    test_repeat_runs_do_not_accumulate_comments()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("all checks passed")
