# Home Assistant for aw-workspace.
#
# Deliberately NOT the stock homeassistant/home-assistant image used directly:
# this one adds two things the stock image can't know about.
#
#   1. `aioamazondevices` baked in — the library the `alexa_devices`
#      integration needs. Home Assistant does install integration
#      requirements at runtime into /config/deps, but that turns the first
#      boot after any config wipe into a silent multi-minute stall where
#      every Echo entity is `unavailable`. The monolith worked around it with
#      an `entrypoint: /bin/sh -c "pip install … && exec /init"` override in
#      aw.json; baking it is the same fix without the override.
#
#   2. A reverse-proxy fixup at boot. aw-workspace reaches this container
#      through its own proxy on a podman network, so Home Assistant sees a
#      forwarded request from an address it doesn't trust and answers 400
#      ("A request from a reverse proxy was received…") for EVERY request.
#      That reads as a broken app, not as a config gap, so the entrypoint
#      guarantees the `http:` keys rather than leaving them to onboarding.
#
# Published by .github/workflows/build.yml as
# ghcr.io/tekflox/aw-app-home-assistant:latest.
FROM homeassistant/home-assistant:stable

# The Amazon Echo / Alexa integration's client library. Kept at the floor the
# monolith pinned (>=14.1.6) and otherwise unconstrained, so a Home Assistant
# release that wants a newer one still resolves.
RUN pip install --no-cache-dir 'aioamazondevices>=14.1.6' \
 || pip install --no-cache-dir --break-system-packages 'aioamazondevices>=14.1.6'

COPY entrypoint.sh /aw-entrypoint.sh
COPY ensure_proxy_config.py /aw-ensure-proxy-config.py
RUN chmod +x /aw-entrypoint.sh

ENTRYPOINT ["/aw-entrypoint.sh"]
