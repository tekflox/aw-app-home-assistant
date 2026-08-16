#!/usr/bin/env python3
"""Guarantee Home Assistant will accept requests from aw-workspace's proxy.

aw-workspace serves this container through a reverse proxy that sits on a
podman network, so every request arrives with ``X-Forwarded-For`` from an
address Home Assistant has never seen. Without ``http.use_x_forwarded_for``
and a matching ``http.trusted_proxies``, HA answers **400** to all of them —
the window renders an error page and the app looks broken rather than
misconfigured.

The proxy's address is not knowable ahead of time (podman hands out a subnet
per network, and it changes when the network is recreated), so the whole
RFC1918 space is trusted. That is the same posture as HA's own documented
docker-behind-a-proxy setup: the container is not directly reachable from
outside the workspace, and aw-workspace has already authenticated the caller
before the request gets this far.

Edits are **textual, in place, and additive**: this rewrites only the ``http:``
block and only when something required is missing, so hand-written config and
comments elsewhere in the file survive. YAML is not round-tripped through a
parser precisely because HA's config is full of ``!include``/``!secret`` tags
that a plain loader would either choke on or silently drop.
"""
from __future__ import annotations

import json
import os
import sys

#: Trusted because the container is only reachable from inside the workspace's
#: own container network. Loopback is here for a direct ``docker exec`` curl.
REQUIRED_PROXIES = [
    "127.0.0.1",
    "::1",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
]

DEFAULT_CONFIG = """# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
"""


def _http_block(existing_proxies: list[str], keep: list[str] | None = None) -> str:
    """Render the ``http:`` block.

    ``existing_proxies`` are kept and the required ranges appended, so a proxy
    someone added by hand is never dropped. ``keep`` is every other line of the
    original block — ``server_port``, ``ssl_certificate``, ``cors_allowed_origins``
    and anything else HA accepts here. Only the two keys this script manages are
    rewritten; everything else is passed through untouched, because silently
    losing a user's TLS config while "fixing" a proxy setting is a far worse
    failure than the 400 this exists to prevent.
    """
    proxies = list(existing_proxies)
    for cidr in REQUIRED_PROXIES:
        if cidr not in proxies:
            proxies.append(cidr)
    lines = [
        "http:",
        "  # Managed by aw-app-home-assistant — aw-workspace proxies this",
        "  # container, so HA must trust the forwarded address or answer 400.",
        "  use_x_forwarded_for: true",
        # SAMEORIGIN blocks the workspace SPA from framing this app's window.
        "  use_x_frame_options: false",
        "  trusted_proxies:",
    ]
    lines += [f"    - {p}" for p in proxies]
    lines += [line.rstrip("\n") for line in (keep or [])]
    return "\n".join(lines) + "\n"


def _find_block(lines: list[str], key: str) -> tuple[int, int] | None:
    """Span ``[start, end)`` of a top-level ``key:`` block, or None.

    A top-level key starts at column 0; the block runs until the next line
    that also starts at column 0 and isn't blank or a comment.
    """
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"{key}:" or line.startswith(f"{key}:"):
            if not line[:1].isspace():
                start = i
                break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            return start, j
    return start, len(lines)


#: Keys inside ``http:`` that this script owns and therefore rewrites. Every
#: other line of the block is preserved verbatim.
_MANAGED_KEYS = ("use_x_forwarded_for:", "use_x_frame_options:", "trusted_proxies:")


def _split_http_block(block: list[str]) -> tuple[list[str], list[str]]:
    """Split an ``http:`` block into (trusted_proxies entries, other lines).

    "Other lines" excludes the ``http:`` header itself, the managed keys, the
    list items under ``trusted_proxies``, and this script's own marker comment
    — so a repeat run doesn't accumulate duplicate comments.
    """
    proxies: list[str] = []
    keep: list[str] = []
    in_proxy_list = False
    for line in block[1:]:  # block[0] is the "http:" header
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("trusted_proxies:"):
            in_proxy_list = True
            continue
        if in_proxy_list and stripped.startswith("- "):
            proxies.append(stripped[2:].strip())
            continue
        in_proxy_list = False
        if stripped.startswith(_MANAGED_KEYS):
            continue
        if stripped.startswith("# Managed by aw-app-home-assistant") or \
                stripped.startswith("# container, so HA must trust"):
            continue
        keep.append(line)
    return proxies, keep


STORAGE_REL = ".storage/http"


def _as_networks(values) -> list[str]:
    """Normalise proxy entries the way HA stores them (``a.b.c.d/32``)."""
    import ipaddress
    out: list[str] = []
    for v in values or []:
        try:
            out.append(str(ipaddress.ip_network(v, strict=False)))
        except ValueError:
            continue
    return out


def ensure_storage(config_dir: str) -> bool | None:
    """Fix the proxy config in ``.storage/http``. None = this HA doesn't use it.

    Modern Home Assistant migrated the ``http:`` integration out of YAML into a
    stored config (``yaml_migration_done``), and this is the file the running
    server actually reads. Editing ``configuration.yaml`` on such a version is
    not merely useless — it is a trap with a very convincing alibi:

    * ``check_config --info http`` reads the YAML, so it happily prints the
      values you wrote and confirms nothing.
    * HA files the YAML under ``pending``, boots on it once as a *trial*, and
      reverts to ``stable`` a few minutes later unless a human confirms the new
      config **in the web UI** — which, when the broken setting is the one that
      makes the web UI reachable, cannot be done. The entry is then marked
      ``"error": "not_promoted"`` and skipped on every future boot, forever.

    Observed 2026-08-16 on HA 2026.8: stable held the pre-migration proxy list,
    pending held the right one with ``not_promoted``, and every request through
    the workspace proxy 400'd while the config looked correct everywhere a
    human would think to check.

    So write ``stable`` directly, and drop any failed ``pending`` so HA has no
    stale trial to skip.
    """
    path = os.path.join(config_dir, STORAGE_REL)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        print(f"aw-entrypoint: {STORAGE_REL} is unreadable — leaving it alone",
              file=sys.stderr)
        return None

    data = doc.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("stable"), dict):
        return None

    stable = data["stable"]
    have = _as_networks(stable.get("trusted_proxies"))
    required = _as_networks(REQUIRED_PROXIES)
    missing = [p for p in required if p not in have]

    changed = False
    if missing or not stable.get("use_x_forwarded_for"):
        stable["trusted_proxies"] = have + missing
        stable["use_x_forwarded_for"] = True
        stable["error"] = None
        stable["error_message"] = None
        changed = True

    # Home Assistant defaults to sending `X-Frame-Options: SAMEORIGIN`, and the
    # workspace SPA frames this app from a DIFFERENT origin (the workspace host
    # vs the app's own subdomain), so the browser blocks the frame and the
    # window renders an empty broken-page box. Nothing is logged anywhere: HA
    # answers 200, the proxy is fine, and only the browser knows why.
    #
    # This was invisible until 2026-08-16 because the reverse-proxy 400 got
    # there first — an error body carries no X-Frame-Options, so the window
    # showed HA's "400: Bad Request" text and looked like a proxy problem
    # alone. Fixing the 400 revealed the second, quieter one underneath.
    #
    # Safe here: the container is only reachable through the workspace's own
    # authenticated edge, which is what decides who may frame it.
    # `is not False` rather than a truthiness check: an ABSENT key means HA's
    # own default, which is on — so a missing key has to be written, not
    # skipped.
    if stable.get("use_x_frame_options") is not False:
        stable["use_x_frame_options"] = False
        changed = True

    # A pending trial that already failed is skipped forever and only confuses
    # the next person reading this file. Drop it once stable is correct.
    if data.get("pending") is not None:
        data["pending"] = None
        changed = True

    if changed:
        _write_json(path, doc)
    return changed


def _write_json(path: str, doc) -> None:
    tmp = f"{path}.aw-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def strip_managed_yaml_block(config_dir: str) -> bool:
    """Remove OUR ``http:`` block from configuration.yaml once storage owns it.

    Leaving it there makes HA raise the ``yaml_still_present_after_migration``
    repair on every boot and re-stage a doomed ``pending`` trial. Only removed
    when the block carries this script's own marker — a block someone wrote by
    hand is theirs, and is left with a warning instead.
    """
    path = os.path.join(config_dir, "configuration.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return False

    span = _find_block(lines, "http")
    if span is None:
        return False
    start, end = span
    block = "".join(lines[start:end])
    if "Managed by aw-app-home-assistant" not in block:
        print("aw-entrypoint: configuration.yaml has a hand-written http: block, "
              "but this Home Assistant reads .storage/http — the YAML block is "
              "ignored and will raise a repair. Left in place.", file=sys.stderr)
        return False

    remaining = "".join(lines[:start] + lines[end:]).rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(remaining)
    return True


def ensure(config_dir: str) -> bool:
    """Return True if the file was changed."""
    path = f"{config_dir}/configuration.yaml"
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        # Fresh volume — HA would write this itself during onboarding, but it
        # needs the http block from the very first request, not after.
        text = DEFAULT_CONFIG

    lines = text.splitlines(keepends=True)
    span = _find_block(lines, "http")

    if span is None:
        new_text = text.rstrip("\n") + "\n\n" + _http_block([])
    else:
        start, end = span
        block = lines[start:end]
        have, keep = _split_http_block(block)
        has_xff = any(
            line.strip().startswith("use_x_forwarded_for:")
            and line.split(":", 1)[1].strip().lower() in ("true", "yes", "on")
            for line in block
        )
        if has_xff and all(cidr in have for cidr in REQUIRED_PROXIES):
            return False
        new_text = "".join(lines[:start]) + _http_block(have, keep) + "".join(lines[end:])

    if new_text == text:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return True


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/config"

    # Storage wins when it exists: it is what the running server reads.
    stored = ensure_storage(target)
    if stored is None:
        changed = ensure(target)
        print(f"aw-entrypoint: reverse-proxy config "
              f"{'updated' if changed else 'already correct'} in "
              f"{target}/configuration.yaml")
    else:
        stripped = strip_managed_yaml_block(target)
        print(f"aw-entrypoint: reverse-proxy config "
              f"{'updated' if stored else 'already correct'} in {STORAGE_REL}"
              f"{' (removed the superseded YAML http: block)' if stripped else ''}")
