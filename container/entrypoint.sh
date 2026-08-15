#!/usr/bin/env sh
# Prepare /config, then hand off to Home Assistant's own s6 init unchanged.
#
# Everything here has to be safe on a /config that is a fresh empty volume AND
# on one restored from another install (the migration case this app was built
# for) — so each step creates what's missing and leaves what's already correct
# alone. A failure here must never stop Home Assistant from booting: a HA that
# comes up with a stale proxy config is debuggable, one that never comes up is
# a blank window with nothing in it.
set -e

CONFIG_DIR="${AW_HA_CONFIG_DIR:-/config}"

mkdir -p "$CONFIG_DIR" "$CONFIG_DIR/themes"

# The default configuration.yaml `!include`s these three, and an !include of a
# missing file is a hard startup failure — so on a fresh volume they have to
# exist before HA reads the config, not after onboarding writes them.
for f in automations.yaml scripts.yaml scenes.yaml; do
    [ -e "$CONFIG_DIR/$f" ] || printf '[]\n' > "$CONFIG_DIR/$f"
done

if ! python3 /aw-ensure-proxy-config.py "$CONFIG_DIR"; then
    echo "aw-entrypoint: WARNING — could not verify the reverse-proxy config in" \
         "$CONFIG_DIR/configuration.yaml. If the UI answers 400 with 'a request" \
         "from a reverse proxy was received', add http.use_x_forwarded_for and" \
         "http.trusted_proxies by hand." >&2
fi

exec /init "$@"
