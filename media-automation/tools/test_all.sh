#!/bin/sh
# Run each independent application's tests in a separate process/environment.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
film_python=${FILM_PYTHON:-python3}
theme_python=${THEME_PYTHON:-python3}
"$film_python" "$root/tools/check_layout.py"
(cd "$root" && "$film_python" -m pytest -q tests)
(cd "$root/apps/emby-theme-worker" && "$theme_python" -m pytest -q tests)
