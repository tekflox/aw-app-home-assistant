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
   never seen, so without `http.use_x_forwarded_for` and a matching
   `http.trusted_proxies` HA answers **400 to every request** — which renders
   as a broken app, not as a config gap. The entrypoint guarantees those keys
   on every boot, additively: it rewrites only the `http:` block, only when
   something required is missing, and keeps any proxy you added yourself.

3. **Fresh-volume seeding.** The default `configuration.yaml` `!include`s
   `automations.yaml` / `scripts.yaml` / `scenes.yaml`, and an `!include` of a
   missing file is a hard startup failure, so the entrypoint creates them.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `auto_start` | `true` | Start the container when the workspace starts. |
| `timezone` | `America/New_York` | IANA zone the *container* runs in. HA's own time zone is separate, in its General settings. |

## Enabling the MCP tools

Home Assistant ships its own MCP server, which is how an agent controls Alexa
without ever holding a token. It is **off by default** and enabling it is
manual, because `/api/mcp` needs a long-lived access token that is specific to
one install and this repo is public.

1. In Home Assistant: **Settings → Devices & Services → Add integration →
   Model Context Protocol Server**.
2. Profile → Security → **Create a long-lived access token**.
3. Edit the *installed* copy of `mcp.json` at
   `/opt/aw-workspace/apps/home-assistant/mcp.json` — paste the token in place
   of `REPLACE_WITH_HA_LONG_LIVED_TOKEN` and set `"enabled": true`.
4. `aw-workspace-cli restart mcp-gateway`, then confirm the `aw__home_assistant__*`
   tools appear.

> **This does not survive an app update.** The installed package dir is
> overwritten wholesale on every version bump, so step 3 resets to the
> placeholder and the HA tools vanish from the gateway until you redo it.
> There's no way around it today: a Tier-2 app runs no workspace-side code, so
> it has nothing that could write the file from the secret store the way
> `aw-app-notion` does. If this becomes annoying, the fix is upstream — either
> config substitution in the app-scan's `mcp.json` read, or splitting a
> one-file Tier-1 companion app out of this one.

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
