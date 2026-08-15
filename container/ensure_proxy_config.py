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
_MANAGED_KEYS = ("use_x_forwarded_for:", "trusted_proxies:")


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
    changed = ensure(target)
    print(
        f"aw-entrypoint: reverse-proxy config {'updated' if changed else 'already correct'}"
        f" in {target}/configuration.yaml"
    )
