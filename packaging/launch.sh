#!/bin/sh
set -eu
data=${XDG_DATA_HOME:-"$HOME/.local/share"}
state=${XDG_STATE_HOME:-"$HOME/.local/state"}
config=${XDG_CONFIG_HOME:-"$HOME/.config"}
app="$data/mavis"
if [ "${1:-}" != "--no-browser" ]; then
    mkdir -p "$state/mavis"
    exec >>"$state/mavis/launcher.log" 2>&1
fi
IFS= read -r release < "$app/current"
export TUBE_WORKSPACE="${TUBE_WORKSPACE:-$app/workspace}"
if [ -r "$config/mavis/billing.env" ]; then
    export MAVIS_BILLING_CONFIG="$config/mavis/billing.env"
fi
exec "$release/.venv/bin/python" "$release/local_studio.py" --port 0 "$@"
