# Local rollout acceptance — 2026-10-03

The reviewed consolidation at `bbad2ba60dab3be999d487183d785d2f5f5499a2` was installed locally. Deployment reference fixes are in `34b73501764e848790789e7066f8bed82b09e626`. Unlike the initial cloud-only validation, this rollout exercised the existing MoviePilot, Theme Worker and Emby services.

## Changes

- Both MoviePilot plugins are installed from the consolidated root manifest through the existing local-plugin mechanism. Their IDs, configuration prefixes and persistent state remain unchanged.
- Theme Worker is rebuilt as a wheel and installed over the existing verified runtime image, preserving audio dependencies, classifier model, FFmpeg and Deno. The installed package and runtime module hashes match the new source.
- Compose now uses `apps/emby-theme-worker` in this checkout. A private deployment override preserves the existing restart policy (`on-failure`) and configured environment. Persistent mount paths, provider choices and schedules remain in place.
- Active clone instructions and the worker's project reference use `media-automation`. ThemeStudio uses the host's bundled music icon; its original SVG remains in the source tree. Historical repository names in `source-snapshots.json` retain provenance.
- Favsync and its film API are retained as independent dependencies. The optional shared-download package remains optional.

## Basic smoke gates

| Gate | Result |
| --- | --- |
| Consolidated layout and plugin identities | Pass |
| Film unified source selection and mocked submission | Pass |
| Film disc rejection, duplicate prevention and library-confirmed writeback | Pass |
| Theme config, existing-file skip and interrupted replacement recovery | 3 selected tests pass |
| Film API with existing authentication | HTTP 200 |
| MoviePilot ThemeStudio proxy and authenticated session | HTTP 200 |
| Authenticated frontend remote entry | HTTP 200 |
| Theme installed wheel and both deployed plugin trees | Source hashes match |
| Theme runtime doctor | Emby authentication, SQLite, media mount, FFmpeg, FFprobe, Deno and yt-dlp pass |
| Theme health | SQLite and scheduler pass; container healthy |
| Persistent Theme state | 1087 item records and 950 library snapshots retained |
| Film plugin configuration | Hash unchanged |

These gates did not trigger additional downloads, theme publication or film completion writes. They are basic rollout smoke checks, not a new full regression run. Mini4K's existing authenticated-browser dependency remains as documented in the index smoke record.

## Cleanup and recovery

After acceptance, both original GitHub repositories (`moviepilot-film-watchlist` and `emby-theme-worker`) were deleted, with authenticated follow-up requests confirming HTTP 404. Their old local working copies were removed. The consolidated repository and Favsync remain available.

Private recovery artifacts retain complete Git bundles, working-tree archives (including local deployment differences), runtime plugin copies, SQLite snapshots and the prior Theme runtime image. Credentials and deployment overrides are kept outside this Git repository. Recovery location and detailed host commands are recorded privately with those artifacts.
