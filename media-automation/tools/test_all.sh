#!/bin/sh
# Run each independent application's tests in a separate process/environment.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
film_python=${FILM_PYTHON:-python3}
theme_python=${THEME_PYTHON:-python3}
export PYTHONPATH="$root/packages/media-capabilities/src:$root/apps/media-search:$root/apps/media-download-mcp:$root/tests${PYTHONPATH:+:$PYTHONPATH}"
status=0
"$film_python" "$root/tools/check_layout.py" || status=1
(cd "$root" && "$film_python" -m pytest -q tests) || status=1
# Independent processes preserve the no-FilmWatchlist host contract and isolate stubs.
for script in smoke_acquisition smoke_capability_host smoke_search_fallback smoke_mini4k_login smoke_media_archive; do
    "$film_python" "$root/tests/$script.py" || status=1
done
"$film_python" -c 'import conftest, smoke_legacy_submission' || status=1
(cd "$root/apps/emby-theme-worker" && "$theme_python" -m pytest -q tests) || status=1
exit "$status"
