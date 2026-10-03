# bili-sync flat output variant

Standalone Docker build of [bili-sync](https://github.com/amtoaer/bili-sync) v2.11.1 with an optional flat-output patch. It needs neither Favsync Core nor another source adapter.

This directory is the canonical Bili build/patch subsection in the Favsync
workspace. `UPSTREAM.json` records the exact source and variant provenance; the
old standalone repository and its history have not been changed or removed.
The root `Dockerfile.bili-sync` and patch paths are compatibility symlinks, so
existing root Compose builds retain their old state/output mounts. The independent
Compose file below is for a separately configured deployment; do not switch an
existing deployment to its relative `state/` directory without mapping old mounts.
No upstream source copy, second scheduler, or Favsync-owned Bili database is added.

## Start

```sh
cp .env.example .env
mkdir -p state downloads
docker compose build
docker compose up -d
```

Set `DOWNLOAD_ROOT` to an absolute host directory before deployment. Set `BILI_BIND` to an interface reachable only by authorized users, and configure the account and favorite folders through bili-sync WebUI at port 12345. Local SQLite state is persisted in `state/`. The environment variable `BILI_SYNC_FLAT_OUTPUT=1` enables flat media filenames. `BILI_SYNC_MIN_FREE_BYTES` prevents starting a new page download below the configured free-space threshold.

The patch is pinned to upstream commit `791dd57f2321d9093c39f38bee8528f249b06e04` and changes local default names, skip settings and scan interval in addition to flat output. Review these defaults before use. It has not been accepted upstream; do not assume it works against a newer bili-sync release. The local build and account-level download behavior need to be verified on the target host.

## Flat-output correctness and compatibility

New flat-output pages reserve a stable filename before downloading. A hidden
`.bili-sync-flat/assignments/` ledger and an OS file lock prevent concurrent pages
from choosing the same name. The usual name is preserved; collisions use
`name_BVID.mp4`, then `name_BVID_2.mp4`, and so on. Multi-page names keep `_P01`.
Existing files and nonempty database `page.path` values also reserve their names,
even when an older media file is missing. Existing `page.path` strings are never
renamed or normalized by this change. Historical pages keep their existing
publication behavior; this does not migrate or repair old media.
For collision comparison only, existing path prefixes and `..` components are
resolved, so legacy aliases also occupy the same target. Unresolvable historical
symlink prefixes fail closed; the original database text remains unchanged.

The new path is committed to SQLite before network I/O. Downloads are staged in
the destination filesystem and published with an atomic, no-replace hard link.
A retry after publication uses the same assignment and accepts an existing target
only when its bytes match the completed download. Different contents fail closed.
Managed assignments retain this protection if flat output is later disabled.
Reservation or DB failures propagate as page failures instead of completing the
parent video silently.

Keep the hidden ledger together with the download directory and back up SQLite
state with it. Do not delete assignment records to free space: they are small,
and they protect names across failed downloads and restarts. Normal staging files
are removed automatically; abrupt termination can leave orphan `.part` files in
`.bili-sync-flat/staging/`. Only remove those with every bili-sync process stopped.
No completed media is kept as a second hidden copy.

This implementation targets the Linux Docker deployment and requires working OS
file locks, same-filesystem hard links, and directory fsync. Unsupported storage
fails closed rather than falling back to overwriting. NAS/NFS/SMB behavior still
needs validation on the target mount; no live download or deployment is implied
by the offline tests. New allocations scan reservation records and stored paths;
large-library allocation cost has not been benchmarked. Other applications writing
inside the download directory are not coordinated, but final media publication
will not replace their files.

## Offline regression checks

Use Rust 1.94 and a local checkout containing the pinned upstream commit:

```sh
./scripts/test-flat-output.sh /path/to/bili-sync
# Also type-check the full patched application and run the SQLite tests,
# using already cached Cargo dependencies only:
./scripts/test-flat-output.sh /path/to/bili-sync --cargo
```

The script archives the exact pinned commit into a temporary directory, checks and
applies the shipped patch, and runs its standalone tests without modifying the
input checkout. Coverage includes concurrent same-title pages, concurrent retries,
process death while holding the lock, interrupted staging, retry after publication
before the status commit, historical/missing paths, symlinks, corrupt ledgers, and
refusal to replace unrelated media. `--cargo` adds SQLite compare-and-set tests and
full application type checking. It does not run upstream network/media tests.
