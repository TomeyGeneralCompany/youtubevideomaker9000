#!/bin/sh
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data=${XDG_DATA_HOME:-"$HOME/.local/share"}
state=${XDG_STATE_HOME:-"$HOME/.local/state"}
config=${XDG_CONFIG_HOME:-"$HOME/.config"}
app="$data/mavis"
for command in python3 ffmpeg ffprobe; do
    command -v "$command" >/dev/null || { echo "Install $command first." >&2; exit 1; }
done
mkdir -p "$app/releases" "$data/applications" "$state/mavis" "$config/mavis" "$HOME/.local/bin"
release=$(mktemp -d "$app/releases/release.XXXXXXXX")
trap 'rm -rf -- "$release"' EXIT
cp -R "$src/app/." "$release/"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install -r "$release/requirements.txt"
"$release/.venv/bin/python" "$release/local_studio.py" --help >/dev/null
printf '%s\n' "$release" > "$app/current.new"
mv -f "$app/current.new" "$app/current"
trap - EXIT
install -m 755 "$src/launch.sh" "$HOME/.local/bin/mavis"
install -m 644 "$release/icon.svg" "$app/icon.svg"
if [ ! -f "$config/mavis/billing.env" ]; then
    install -m 600 "$src/billing.env" "$config/mavis/billing.env"
fi
desktop_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\\\\\/g; s/["`$]/\\\\&/g; s/%/%%/g'
}
cat > "$data/applications/mavis.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=MAVIS
Comment=Local video production studio
Exec="$(desktop_escape "$HOME/.local/bin/mavis")"
Icon=$app/icon.svg
Terminal=false
Categories=AudioVideo;Video;
DESKTOP
printf '%s\n' "Installed MAVIS. Open it from your application menu or run $HOME/.local/bin/mavis."
