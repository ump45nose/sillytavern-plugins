# Media automation

FilmWatchlist and Emby Theme share a maintenance tree while keeping their original plugin IDs, Python packages, runtime state and independent entry points.

## Layout and entry points

- `package.v2.json` and `plugins.v2/filmwatchlist` retain MoviePilot's repository-root installation contract and the `FilmWatchlist` class/config prefix
- `plugins.v2/themestudio` contains the `ThemeStudio` plugin and its existing frontend distribution; it remains a thin proxy to `/run/theme-worker/control.sock`
- `apps/emby-theme-worker` is an independently installable Python project, CLI and Docker build context, with its original config, compose, docs, tests and state schema
- `frontends/theme-studio` contains the Vue source and lockfile; its build writes to the root ThemeStudio plugin distribution
- Compatibility links under `apps/emby-theme-worker/moviepilot` retain the previous frontend, plugin and manifest paths for existing Unix-based tooling

The Film plugin never imports the Theme worker or its audio dependencies. The Theme worker never imports MoviePilot or FilmWatchlist. There is no new root Python package, shared database, scheduler or always-on service.

## FilmWatchlist

See [the original plugin guide](docs/filmwatchlist.md). Install from this repository root using MoviePilot's local plugin mechanism; the plugin IDs, directory names, config keys and plugin-data storage remain unchanged. Native host recognition, search and download operations remain MoviePilot responsibilities; the existing P115 helper continues to own its task services.

The plugin now separates candidate policy/submission (`workflow.py`), saved-task recovery/writeback (`observe.py`) and compatible record helpers (`state.py`). Both PT policies use one persisted-intent submission function. Uncertain submissions remain pending until observed; a missing task alone never authorizes another submission. Recovery runs before source enumeration and M-Team availability checks.

New tasks freeze media/season/source/target facts. A mutable source is rechecked before completion writeback; source outages only postpone that writeback. Completed-source corrections preserve the old receipt in `completed_history`, and new candidate IDs do not encode share URLs or extraction codes. Legacy candidate IDs, records and download handles remain readable. Older TV records can enrich missing episode membership by saved media IDs while cloud task recovery remains independent.

## Theme worker and Studio

See the [Theme application guide](apps/emby-theme-worker/README.md). Its normal standalone installation remains:

```sh
cd apps/emby-theme-worker
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
emby-theme-worker --help
```

The Docker build context remains `apps/emby-theme-worker`; use the application's documented external model context and image build requirements. Existing runtime mount paths and socket/config paths are retained. No state or credential files are relocated by this layout.

The optional `shared-downloads` extra uses the separately built `favsync-downloads==0.1.0` package from the Favsync maintenance tree. Install its verified local wheel first, then the extra, following the application guide. Default standalone installation retains a compatibility transport path; no unpublished dependency is mandatory. Selected audio transfer can use that package; theme search, scoring, full-track/crop decisions, ffmpeg, file ownership and Emby publication stay in the Theme application.

Full-track duration remains the default. Audio generation, preview and hash readback share one output budget; oversized output is rejected instead of silently truncated. Manual upload requests retain their prior request-size limit.

## Frontend build

```sh
cd frontends/theme-studio
npm ci
npm run build
```

Prebuilt MoviePilot distribution files are tracked under `plugins.v2/themestudio/dist`. The old application-local frontend path resolves to this same source tree.

## Offline verification

Film tests use small MoviePilot host stubs; Theme tests use fixtures, temporary SQLite state and stubbed providers. They do not verify a deployed MoviePilot/P115/Emby instance.

```sh
python -m pip install -r requirements-test.txt
python -m pytest -q tests
# Use independently prepared interpreters when dependencies are separate:
FILM_PYTHON=/path/to/film-venv/bin/python \
THEME_PYTHON=/path/to/theme-venv/bin/python tools/test_all.sh
```

`tools/check_layout.py` checks root manifests, plugin identities, compatibility paths, independent worker metadata and frontend output location. Source provenance is in `docs/source-snapshots.json`; detailed validation and remaining limits are in `docs/validation.md`.

## Publication and compatibility limits

This tree does not perform a production migration, remote-repository rename, release or deployment. Existing release/icon URLs remain unchanged until a publication target is selected. Film table/API physical migration is outside this change.

Favsync's current film API has no conditional revision write, so identity readback immediately before PATCH narrows but cannot eliminate a concurrent source-change race. Theme's automatic first-file publication still has its pre-existing file-to-ownership-DB crash window; explicit replacement/manual-apply recovery has separate durable journal coverage.

## Source and licenses

The original repositories and exact imported commits are recorded in `docs/source-snapshots.json`. Theme's MIT license remains scoped to its application under `apps/emby-theme-worker/LICENSE`; ThemeStudio third-party notices remain beside that plugin. FilmWatchlist's source had no separate license file. This consolidation does not assign Theme's license to FilmWatchlist or the entire maintenance tree.
