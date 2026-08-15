---
name: aw-home-assistant
description: Control and query this workspace's Home Assistant — Alexa/Echo devices, media playback, TTS announcements, device state and sensors. Use when the user asks to play music/radio, control Alexa devices, check what's playing, query home sensors, or manage Home Assistant.
---

# aw-home-assistant

Home Assistant runs as the **`home-assistant`** app in this workspace — a
Tier-2 container app (`aw-app-home-assistant`) listening on port **8123**.

| | |
|---|---|
| Container | `aw-app-home-assistant` |
| From inside another app container | `http://aw-app-home-assistant:8123` |
| From the workspace container | `http://aw-app-home-assistant:8123` |
| Config dir on the host | `/opt/aw-workspace/.aw-workspace/data/home-assistant/config` |
| Config dir inside the container | `/config` |
| UI | the **Home Assistant** card in the Apps grid |

> **There is no `localhost:8123`.** The monolith ran HA in a shared network
> namespace, so every old note says `http://localhost:8123`; here it is its own
> container on the workspace's podman network. Use the container name.

---

## Authentication

### Through MCP (preferred, no token in your hands)

Home Assistant serves its own MCP endpoint, aggregated by `aw-mcp-gateway`.
Call the `aw__home_assistant__*` tools directly — the bearer token lives in
the gateway's config and never enters an agent's context.

**19 tools, verified served on 2026-08-15:**

| Tool | Use it for |
|---|---|
| `GetLiveContext` | **Start here.** The current state of every exposed device — what's playing, what's on, who's home. Ask this before acting rather than guessing entity IDs. |
| `GetDateTime` | HA's own clock/timezone. |
| `HassTurnOn` / `HassTurnOff` | Switches, lights, media players, anything toggleable. |
| `HassMediaPause` / `HassMediaUnpause` | Pause/resume playback. |
| `HassMediaNext` / `HassMediaPrevious` | Skip tracks. |
| `HassMediaSearchAndPlay` | Play something by name ("toca Djavan"). |
| `HassSetVolume` / `HassSetVolumeRelative` | Absolute (0–100) / relative volume. |
| `HassMediaPlayerMute` / `HassMediaPlayerUnmute` | Mute toggle. |
| `HassBroadcast` | Announce a message on the speakers. |
| `HassCancelAllTimers` | Kill running timers on a device. |
| `todo_get_items`, `HassListAddItem`, `HassListCompleteItem`, `HassListRemoveItem` | Shopping / to-do lists. |

These are HA's **intent** API: they take natural names ("Echo Dot", "the
bedroom"), not `entity_id`s, and they only reach entities HA has *exposed* to
assistants (Settings → Voice assistants → Expose). An entity that exists in
the REST `/api/states` dump but isn't exposed is invisible to every tool above
— that asymmetry is the usual reason an MCP call says it can't find a device
you can plainly see.

**What MCP cannot do — reach for REST instead:**

- **`alexa_devices.send_text_command`** has no MCP equivalent. Anything phrased
  as a spoken command to Alexa — TuneIn radio, "play Spotify", built-in skills
  — goes through the REST recipe below. This is the single biggest gap.
- `send_sound` / `send_info_skill`, likewise.
- Admin work: reloading a config entry, the device/entity registries,
  inspecting integrations.

**If the tools aren't in your tool list**, check in this order:

1. Is your session older than the app? An agent's tool list is snapshotted at
   session start — a session that began before the app was installed will
   never see them. Start a new session.
2. Did the app just update? An update overwrites
   `/opt/aw-workspace/apps/home-assistant/mcp.json` back to its disabled
   placeholder and the tools vanish from the gateway. Re-apply the token per
   the app's README, then `aw-workspace-cli restart mcp-gateway`.
3. Otherwise fall back to the REST API below — it needs no gateway.

### Raw REST API

Every REST call needs a long-lived access token. Create one in the HA UI
(profile → Security → Long-lived access tokens) and keep it in the workspace
secret store rather than a file:

```bash
aw-workspace-cli secrets read home_assistant_token
```

Then:

```bash
curl -s "http://aw-app-home-assistant:8123/api/" -H "Authorization: Bearer $TOKEN"
# → {"message":"API running."}   means auth works
```

> **Gotcha carried over from the monolith (cost hours on 2026-07-12):** if you
> ever hand-inject a token into `/config/.storage/auth`, HA only picks it up if
> the file is written **before** HA boots — its own debounced auto-save will
> otherwise overwrite your edit back to in-memory state and silently discard
> it. Order is: write → restart the app → wait for full boot (~30–45 s) → test.
> Creating a token through the UI has none of this problem; prefer it.

---

## Device inventory

Migrated from the monolith install on 2026-08-15, so device and entity IDs are
unchanged from the old notes.

### Amazon Echo devices (`alexa_devices` integration)

| Friendly name | `device_id` | `entity_id` (media_player) | Notes |
|---|---|---|---|
| Frederico's Echo Dot | `ca4a3636b874017f342f02cabf8b03c2` | `media_player.frederico_s_echo_dot` | Main speaker; "Ecodote" = this device |
| Frederico's 2nd Echo Dot | `5d38b4c085b289d49a3fa6c20c0f44fa` | `media_player.frederico_s_2nd_echo_dot` | Often unavailable |
| Frederico's Echo Show quarto | `91ada943d3f05d1ccbfcb78171569eaa` | `media_player.frederico_s_echo_show_quarto` | Bedroom |
| Frederico's Echo Show 10 | `f7295df16f6eeee2b1edc8a21b986cae` | `media_player.frederico_s_echo_show_10` | |

Amazon account: `fredericodiaswu@gmail.com`.
Integration config-entry ID: `01KVY9196FGN0S630R3TAP5DN0`.

### Non-Amazon Alexa-linked devices (unavailable most of the time)

| Name | `device_id` | Notes |
|---|---|---|
| Frederico's WF-1000XM5 | `6156b9612bb55a558e2a6a877f7d9766` | Sony headphones |
| Frederico's Voice in a Can for iOS | `4dc10f005727c20987a0bba803884d57` | Atadore app |
| Frederico's Voice in a can for Apple Watch | `3205af65b67ef42e0cd177e8f9eca441` | Atadore app |
| Frederico's 2nd Voice in a can for Apple Watch | `0e732a7267460a448dd45b7c629737b7` | Atadore app |

> `media_player.everywhere` is a virtual group — plays on all Echo devices at
> once. `media_player.bed_time` is another group.

**Lights are not integrated** (as of 2026-06-27; Frederico removed them). When
they come back, document the entity IDs here.

---

## Known issue: `alexa_devices` drops to unavailable

**Symptom:** every Alexa entity reads `unavailable`; `send_text_command`
returns 500 "Entry not loaded".

**Cause:** the integration talks to Amazon's cloud, and Amazon intermittently
answers `Service Unavailable`. Transient — it reconnects on its own within
minutes.

**Force a reconnect:**

```bash
curl -s -X POST \
  "http://aw-app-home-assistant:8123/api/config/config_entries/entry/01KVY9196FGN0S630R3TAP5DN0/reload" \
  -H "Authorization: Bearer $TOKEN"
# → {"require_restart":false}
```

Wait ~10 s and re-check; if still unavailable, wait another 30 s and retry.

**Don't trust the displayed state to decide whether a command landed.** On
2026-06-27 a `send_text_command` sent while entities showed "unavailable" went
through — the Echo Dot started playing — and HA's state lagged ~3 minutes
before catching up to `playing`.

---

## API recipes

All examples assume `TOKEN` is set and use the container hostname.

### What's currently playing

```bash
curl -s "http://aw-app-home-assistant:8123/api/states/media_player.frederico_s_echo_dot" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
s = json.load(sys.stdin); a = s.get('attributes', {})
print('State:', s['state'])
print('Title:', a.get('media_title'))
print('Artist:', a.get('media_artist'))
print('Volume:', a.get('volume_level'))
"
```

### Play radio on TuneIn (Alexa text command)

`send_text_command` takes a **`device_id`**, not an `entity_id`:

```bash
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/alexa_devices/send_text_command" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "device_id": "ca4a3636b874017f342f02cabf8b03c2",
    "text_command": "play JB FM on TuneIn"
  }'
# Returns [] on success (empty list = HA accepted the call)
```

Other phrasings: `"play Rádio Nacional on TuneIn"`, `"play CBN on TuneIn"`,
`"play Spotify"`, `"play playlist [name] on Spotify"`.

### Pause / resume / volume

```bash
# Pause
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/media_player/media_pause" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "media_player.frederico_s_echo_dot"}'

# Resume
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/media_player/media_play" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "media_player.frederico_s_echo_dot"}'

# Volume (0.0–1.0)
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/media_player/volume_set" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "media_player.frederico_s_echo_dot", "volume_level": 0.5}'
```

### TTS / announcements

```bash
# Speak
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/notify/frederico_s_echo_dot_speak" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message": "Olá, Frederico!"}'

# Announce (louder, interrupts playback)
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/notify/frederico_s_echo_dot_announce" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message": "Sua reunião começa em 5 minutos."}'
```

### All device states at once

```bash
curl -s "http://aw-app-home-assistant:8123/api/states" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys, json
for s in json.load(sys.stdin):
    if any(x in s['entity_id'] for x in ['echo','alexa','voice_in_a_can','wf_1000']):
        print(s['state'], s['entity_id'])
"
```

### Do Not Disturb / next alarm

```bash
curl -s -X POST "http://aw-app-home-assistant:8123/api/services/switch/turn_on" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "switch.frederico_s_echo_dot_do_not_disturb"}'

curl -s "http://aw-app-home-assistant:8123/api/states/sensor.frederico_s_echo_dot_next_alarm" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])"
```

---

## `alexa_devices` services

| Service | Key fields | What it does |
|---|---|---|
| `alexa_devices.send_text_command` | `device_id`, `text_command` | Simulate a voice command to Alexa |
| `alexa_devices.send_sound` | `device_id`, `sound` | Play a sound effect (doorbell, chime, …) |
| `alexa_devices.send_info_skill` | `device_id`, `info_skill` | Fire a built-in skill: `weather`, `date`, `tell_joke`, `good_morning`, `goodnight`, `flash_briefing`, … |

---

## Operating the app

```bash
aw-workspace-cli apps home-assistant     # status
aw-workspace-cli restart home-assistant  # restart (wait ~30-45s for a full boot)
aw-workspace-cli logs home-assistant -f  # follow HA's log
```

`docker exec -it aw-app-home-assistant bash` for a shell inside the container.
Note that `aw-workspace-cli` and the container runtime both live in the
**workspace container** — an agent in a runner container reaches them through
the `/api/terminals` route, not by running them locally.

### Where the config actually lives

`/config` inside the container is a bind mount of
`/opt/aw-workspace/.aw-workspace/data/home-assistant/config` on the workspace
disk. It survives app updates, container recreation and workspace redeploys.
The `http:` block in `configuration.yaml` is maintained by the app's
entrypoint on every boot — Home Assistant sits behind aw-workspace's reverse
proxy and answers **400** to every request without it, so don't delete
`use_x_forwarded_for` / `trusted_proxies` from that file.
