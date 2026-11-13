#!/bin/sh
set -eu
source_dir=/usr/share/mavis
data=${XDG_DATA_HOME:-"$HOME/.local/share"}/mavis
mkdir -p "$data"
export TUBE_WORKSPACE="${TUBE_WORKSPACE:-$data/workspace}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
(
    flock 9
    if ! cmp -s "$source_dir/requirements.txt" "$data/.installed-requirements" || [ ! -x "$data/runtime/bin/python" ]; then
        python3 -m venv "$data/runtime"
        "$data/runtime/bin/python" -m pip install -r "$source_dir/requirements.txt"
        cp "$source_dir/requirements.txt" "$data/.installed-requirements"
    fi
) 9>"$data/.install-lock"
exec "$data/runtime/bin/python" "$source_dir/local_studio.py" --port 0 "$@"
