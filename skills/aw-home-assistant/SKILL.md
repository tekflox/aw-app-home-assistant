---
name: aw-home-assistant
description: Control and query this workspace's Home Assistant — lights, switches, speakers, media playback, TTS announcements, sensors and device state, plus Amazon Alexa/Echo devices. Use when the user asks to play music/radio, control a device or a room, check what's playing, query home sensors, or manage Home Assistant.
---

# aw-home-assistant

Home Assistant runs as the **`home-assistant`** app — a Tier-2 container app
(`aw-app-home-assistant`) listening on port **8123**.

| | |
|---|---|
| Container | `aw-app-home-assistant` |
| Base URL from any other container | `http://aw-app-home-assistant:8123` |
| Config dir on the workspace disk | `<AW_WORKSPACE_HOME>/data/home-assistant/config` |
| Config dir inside the container | `/config` |
| UI | the **Home Assistant** card in the Apps grid |

> **There is no `localhost:8123`.** Notes written against the older
> `agentic-workspace` monolith all say that, because Home Assistant shared a
> network namespace with everything else there. Here it is its own container —
> always address it by container name.

**Nothing in this skill is specific to one install.** Entity IDs, device IDs,
which integrations exist and which devices are present all come from *your*
Home Assistant. Every recipe below starts by discovering them rather than
assuming them.

---

## Authentication

### Through MCP (preferred — no token in your hands)

Home Assistant serves its own MCP endpoint, aggregated by `aw-mcp-gateway`.
Call the `aw__home_assistant__*` tools directly; the credential lives in the
gateway's config and never enters an agent's context.

| Tool | Use it for |
|---|---|
| `GetLiveContext` | **Start here.** Current state of every exposed device — what's playing, what's on, who's home. Ask this instead of guessing entity IDs. |
| `GetDateTime` | Home Assistant's own clock and time zone. |
| `HassTurnOn` / `HassTurnOff` | Lights, switches, media players, anything toggleable. |
| `HassMediaPause` / `HassMediaUnpause` | Pause / resume playback. |
| `HassMediaNext` / `HassMediaPrevious` | Skip tracks. |
| `HassMediaSearchAndPlay` | Play something by name. |
| `HassSetVolume` / `HassSetVolumeRelative` | Absolute (0–100) / relative volume. |
| `HassMediaPlayerMute` / `HassMediaPlayerUnmute` | Mute toggle. |
| `HassBroadcast` | Announce a message on the speakers. |
| `HassCancelAllTimers` | Cancel running timers on a device. |
| `todo_get_items`, `HassListAddItem`, `HassListCompleteItem`, `HassListRemoveItem` | Shopping / to-do lists. |

The exact set depends on your Home Assistant version and which integrations
are loaded — the list above is what a stock install exposes.

These are HA's **intent** API: they take natural names ("the kitchen light",
"bedroom speaker"), not `entity_id`s, and they only reach entities Home
Assistant has *exposed* to assistants (Settings → Voice assistants → Expose).
An entity that shows up plainly in the REST `/api/states` dump can therefore
be invisible to every tool above — that asymmetry is the usual reason a tool
says it can't find a device you can see, and it is an exposure setting, not a
bug.

**What MCP cannot do — use REST instead:**

- **Vendor-specific services.** Anything under a `<integration>.<service>`
  name has no MCP equivalent. For Amazon Echo devices that means
  `alexa_devices.send_text_command` — every spoken-command feature (TuneIn
  radio, "play Spotify", built-in skills) is REST-only. This is the largest
  gap between the two surfaces.
- **Admin work.** Reloading a config entry, the device/entity registries,
  inspecting or repairing integrations.

**If the tools aren't in your tool list**, check in this order:

1. **Is your session older than the app?** An agent's tool list is
   snapshotted at session start — a session that began before the app was
   installed or configured will never see them. Start a new session.
2. **Is the token set?** App Settings → *Home Assistant access token*. Empty
   means the renderer deliberately disabled the upstream. See the app README.
3. Otherwise use the REST API below — it needs no gateway.

### Raw REST API

Every REST call needs a long-lived access token: Home Assistant → your
profile → Security → **Long-lived access tokens**. The app already stores one
in its settings for the MCP upstream; keep any other in the workspace secret
store rather than a file.

```bash
curl -s "http://aw-app-home-assistant:8123/api/" -H "Authorization: Bearer $TOKEN"
# → {"message":"API running."}   means auth works
```

> **Don't hand-inject tokens into `/config/.storage/auth`.** Home Assistant
> only picks up a manually written token if the file changed *before* HA
> booted — its own debounced auto-save otherwise overwrites your edit back to
> in-memory state and silently discards it. If you ever must: write → restart
> the app → wait for a full boot (~30–45 s) → test. Creating a token through
> the UI has none of this problem.

---

## Discovering what this install actually has

Do this first, every time. Don't assume an entity exists.

```bash
H=http://aw-app-home-assistant:8123

# Every entity, grouped by domain
curl -s "$H/api/states" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json, collections
by = collections.defaultdict(list)
for s in json.load(sys.stdin):
    by[s['entity_id'].split('.')[0]].append((s['state'], s['entity_id']))
for domain in sorted(by):
    print(f'--- {domain} ({len(by[domain])}) ---')
    for state, eid in sorted(by[domain]): print(f'  {state:<12} {eid}')
"

# Which services are callable (this is where vendor integrations show up)
curl -s "$H/api/services" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
for d in json.load(sys.stdin):
    print(d['domain'] + ':', ', '.join(sorted(d['services'])))
"
```

Some services key off a **`device_id`**, not an `entity_id` (Amazon's
`alexa_devices` is one). Device IDs aren't in the REST API — read them over
the WebSocket API:

```bash
python3 - <<'PY'
import asyncio, json, os, websockets     # pip install websockets
async def main():
    async with websockets.connect("ws://aw-app-home-assistant:8123/api/websocket") as ws:
        await ws.recv()                                    # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": os.environ["TOKEN"]}))
        await ws.recv()                                    # auth_ok
        await ws.send(json.dumps({"id": 1, "type": "config/device_registry/list"}))
        for d in json.loads(await ws.recv())["result"]:
            print(d["id"], "|", d.get("name_by_user") or d.get("name"))
asyncio.run(main())
PY
```

---

## API recipes

### Read the state of one entity

```bash
curl -s "$H/api/states/<entity_id>" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
s = json.load(sys.stdin); a = s.get('attributes', {})
print('State:', s['state'])
for k in ('friendly_name', 'media_title', 'media_artist', 'volume_level'):
    if a.get(k) is not None: print(f'{k}:', a[k])
"
```

### Call any service

Every control below is the same shape — `POST /api/services/<domain>/<service>`
with the target in the body. `[]` or a list of changed states means accepted.

```bash
curl -s -X POST "$H/api/services/<domain>/<service>" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "<entity_id>"}'
```

```bash
# Turn something on / off
-d '{"entity_id": "light.kitchen"}'                     # homeassistant/turn_on

# Pause / resume playback                                media_player/media_pause
-d '{"entity_id": "media_player.living_room"}'

# Volume, 0.0–1.0                                        media_player/volume_set
-d '{"entity_id": "media_player.living_room", "volume_level": 0.5}'

# Speak on a speaker                                     notify/send_message
-d '{"entity_id": "notify.<speaker>_speak", "message": "Dinner is ready"}'
```

### Amazon Echo: spoken commands

Only if the `alexa_devices` integration is set up. Note it takes `device_id`:

```bash
curl -s -X POST "$H/api/services/alexa_devices/send_text_command" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"device_id": "<device_id>", "text_command": "play JB FM on TuneIn"}'
# Returns [] on success
```

Its three services: `send_text_command` (simulate a voice command),
`send_sound` (a sound effect), `send_info_skill` (`weather`, `date`,
`tell_joke`, `good_morning`, `goodnight`, `flash_briefing`, …).

---

## Cloud-backed integrations go `unavailable` — and it's usually transient

Integrations that talk to a vendor cloud (Amazon's `alexa_devices` is the
common one here) drop every entity to `unavailable` when that cloud returns an
error, then recover on their own within minutes. Symptoms: all entities
`unavailable`, a service call returning 500 "Entry not loaded".

**First: wait.** These recover on their own, and the cheap-looking fix below
can make things worse.

Check the config entry's own state before touching anything — it tells you
whether the integration is healthy and merely out of data (`loaded`) or
actually broken (`setup_error`):

```bash
curl -s "$H/api/config/config_entries/entry" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys, json
for e in json.load(sys.stdin): print(e['entry_id'], e['domain'], e['title'], e['state'])
"
```

> **Don't reload a `loaded` entry to 'force a reconnect'.** Reloading tears
> the integration down and sets it up again, and setup re-fetches everything
> from the vendor cloud — the same cloud that is currently failing. Verified
> on 2026-08-15 with `alexa_devices`: one device was working fine, a reload
> was issued, setup died inside `get_communication_preferences` with
> *"Setup of config entry … cancelled"*, and the entry went from `loaded` to
> **`setup_error` with every entity unavailable**. It never recovered on its
> own, and a second reload didn't help either. A reload trades a partial
> outage for a total one.

**Recovery, in order:**

1. **Wait.** A `loaded` entry with stale entities usually catches up within
   minutes.
2. **Restart the app** — `aw-workspace-cli restart home-assistant`, then allow
   ~2 minutes. Integrations are set up fresh on boot, and this is what
   actually brought the `setup_error` entry back above.
3. Reload the entry only if it is *already* `setup_error` — i.e. when there is
   nothing left to lose.

> **Don't use the displayed state to decide whether a command landed.** A
> command sent while entities read `unavailable` can still go through, with HA
> catching up minutes later. Observed lagging ~3 minutes. Judge by what the
> device actually did.

---

## Operating the app

```bash
aw-workspace-cli apps home-assistant     # status
aw-workspace-cli restart home-assistant  # restart (allow ~30-45s for a full boot)
aw-workspace-cli logs home-assistant -f  # follow HA's log
```

`docker exec -it aw-app-home-assistant bash` for a shell inside it. Both the
CLI and the container runtime live in the **workspace container** — an agent
running in a runner container reaches them through the `/api/terminals` route,
not by running them locally.

### Where the config actually lives

`/config` inside the container is a bind mount of
`<AW_WORKSPACE_HOME>/data/home-assistant/config` on the workspace disk, so it
survives app updates, container recreation and workspace redeploys.

The `http:` block in `configuration.yaml` is maintained by the app's
entrypoint on every boot. Home Assistant sits behind aw-workspace's reverse
proxy and answers **400 to every request** without
`use_x_forwarded_for` / `trusted_proxies` — don't remove them. If the window
ever renders an error page rather than the UI, check that block before
anything else.
