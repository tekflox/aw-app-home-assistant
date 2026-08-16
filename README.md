# aw-app-home-assistant

Home Assistant as an aw-workspace app. Tier-2 (container): a Home Assistant
image on port **8123**, reverse-proxied by the workspace, opening as a window
from the Apps grid.

Ported from the `agentic-workspace` monolith's `aw-custom-home-assistant`
custom app (`src/config/aw.json`) on 2026-08-15.

| | |
|---|---|
| App id | `home-assistant` |
| Image | `ghcr.io/tekflox/aw-app-home-assistant:latest` |
| Container | `aw-app-home-assistant` |
| Port | 8123 |
| Config volume | `$AW_APP_DATA/config` → `/config` |
| Capabilities | `containers:manage`, `fs:workspace-data` |

## What this image adds over stock `homeassistant/home-assistant`

1. **`aioamazondevices` baked in** — the client library the `alexa_devices`
   integration needs. HA installs integration requirements at runtime into
   `/config/deps`, but that makes the first boot after a config wipe a silent
   multi-minute stall with every Echo entity `unavailable`. The monolith
   worked around it with an `entrypoint: /bin/sh -c "pip install … && exec
   /init"` override in `aw.json`; baking it is the same fix without an
   override the app framework has no field for.

2. **A reverse-proxy fixup at boot** (`container/ensure_proxy_config.py`).
   aw-workspace proxies this container from a podman network address HA has
   never seen, so without `use_x_forwarded_for` and a matching
   `trusted_proxies` HA answers **400 to every request** — which renders as a
   broken app, not as a config gap. The entrypoint guarantees those settings
   on every boot, additively, keeping any proxy you added yourself.

   **It writes `.storage/http`, not `configuration.yaml`** — see below.

3. **Fresh-volume seeding.** The default `configuration.yaml` `!include`s
   `automations.yaml` / `scripts.yaml` / `scenes.yaml`, and an `!include` of a
   missing file is a hard startup failure, so the entrypoint creates them.

### Why the proxy settings live in `.storage/http`

Modern Home Assistant (2026.8 here) **migrated the `http:` integration out of
YAML** into a stored config — `.storage/http`, holding a `stable` block and an
optional `pending` one. `stable` is what the running server reads.

Editing `configuration.yaml` on such a version isn't just useless, it fails
with an unusually convincing alibi. Every check a person would run agrees with
them, and the app still 400s:

- `check_config --info http` reads the **YAML**, so it prints your values back
  and confirms nothing about what the server is using.
- HA files the YAML config under `pending`, boots on it once as a *trial*, and
  reverts to `stable` a few minutes later unless a human confirms it **in the
  web UI**. When the setting under trial is the one that makes the web UI
  reachable, that confirmation is impossible. The entry is then stamped
  `"error": "not_promoted"` and skipped on every future boot, permanently.
- HA also raises `deprecated_yaml` and `yaml_still_present_after_migration`
  repairs — visible only in that same unreachable UI.

That is exactly what happened on 2026-08-16: `stable` still held the
pre-migration proxy list, `pending` held the correct one marked
`not_promoted`, and the window showed `400: Bad Request` while
`configuration.yaml` looked perfect.

So the entrypoint writes `stable` directly, clears a failed `pending`, and
removes its own now-superseded YAML `http:` block (a hand-written one is left
alone, with a warning). On an older HA with no `.storage/http` it falls back to
managing the YAML block as before.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `auto_start` | `true` | Start the container when the workspace starts. |
| `timezone` | `America/New_York` | IANA zone the *container* runs in. HA's own time zone is separate, in its General settings. |

## Enabling the MCP tools

Home Assistant ships its own MCP server — that's how an agent controls your
home without ever holding a token. Three steps, once:

1. In Home Assistant: **Settings → Devices & Services → Add integration →
   Model Context Protocol Server**.
2. Your profile → Security → **Create a long-lived access token**.
3. Paste it into this app's **Settings → Home Assistant access token**.

The tools appear right after the save. Leave the field empty to keep them off.

### How the token survives an update

The gateway reads `apps/<slug>/mcp.json`, which lives in the installed package
dir — and an app update overwrites that dir wholesale. A token written into
that file directly would last exactly until the next version bump, after which
the upstream stays listed and serves zero tools, with nothing reporting it.

So this app ships **`mcp.template.json`**, not `mcp.json`:

```jsonc
"headers": { "Authorization": "Bearer ${config.mcp_token}" }
```

aw-workspace renders the template into `mcp.json` on every activation and
every config save, resolving `${config.…}` against the app's saved settings —
which live in `<AW_WORKSPACE_HOME>/app-config/home-assistant.json`, outside the
package dir, and which uninstall deliberately keeps. So the credential
survives an update, an uninstall/install and a workspace redeploy with nobody
re-pasting anything. **Never edit the rendered `mcp.json`** — it is
regenerated; edit the setting.

If `mcp_token` is empty the renderer sets `"enabled": false` on that upstream
rather than shipping it with an unresolved placeholder. That is deliberate: an
upstream whose auth header is the literal string `${config.mcp_token}` doesn't
fail loudly, it connects, gets a 401 and serves nothing — which reads as a
broken app instead of a blank field.

Requires aw-workspace with `src/apps/mcp_template.py` (2026-08-15 or later).

## Migrating an existing Home Assistant

Everything HA knows lives in `/config` — onboarding, users, tokens, the device
and entity registries, linked cloud accounts, automations and the recorder
history DB. Moving an install is therefore just moving that directory:

```bash
# on the source host
docker stop <old-ha-container>
tar czf /tmp/ha-config.tar.gz -C /path/to/old/config .

# on the workspace, after installing this app
aw-workspace-cli stop home-assistant
tar xzf ha-config.tar.gz -C /opt/aw-workspace/.aw-workspace/data/home-assistant/config
aw-workspace-cli start home-assistant
```

Stop the source first — the recorder DB is SQLite, and copying it live can
capture a torn WAL. Entity IDs, device IDs and existing long-lived tokens all
carry over unchanged.

## Development

```bash
python tests/validate_manifest.py     # manifest against schemas/aw-app.schema.json
python tests/test_proxy_config.py     # the configuration.yaml fixup
```

Image builds: `gh workflow run build.yml`. Releases (manifest version →
marketplace catalog): push to `master`, then merge the `chore(sync)` PR the
release opens in `tekflox/aw-marketplace`.

## Related

- `skills/aw-home-assistant/SKILL.md` — the agent-facing reference: device
  inventory, REST recipes, the `alexa_devices` outage playbook.
