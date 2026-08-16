---
repo: architecture
path: docs/architecture/aw-app-home-assistant.md
source: generated
edited: false
checksum: sha256:f8aa2c89df319cfc8af0a776d6ce228e9a8bfe7c6c6a5786df4ad85acfebf60f
---
# Home Assistant

- **repo**: aw-app-home-assistant
- **layer**: app-container
- **technologies**: docker
- **health** (derived): planned

Runs Home Assistant in your workspace — control lights, speakers, Alexa/Echo devices and sensors, read the state of your home, and let agents do the same. Opens as a window in the Apps grid, keeps its whole configuration and history on the workspace disk, and comes with the Amazon Alexa integration preinstalled.

## Connections
- `stdio-mcp` → **mcp-gateway** — MCP surface aggregated by the gateway

## MCP tools
- `GetLiveContext`
- `HassBroadcast`
- `HassMediaPause`
- `HassMediaSearchAndPlay`
- `HassMediaUnpause`
- `HassSetVolume`
- `HassTurnOff`
- `HassTurnOn`

## Requirements
_none documented_
