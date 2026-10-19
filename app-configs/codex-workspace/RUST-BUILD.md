# NAS Rust build storage

Rust source remains in its existing repository. Build intermediates go to
the SSD under `/vol2/1000/BuildCache/rust`, outside Docker service data.

The installed Cargo toolchains support `build.build-dir` and the
`{workspace-path-hash}` template. Install `cargo-ssd.toml` as
`/home/yuwk/.cargo/config.toml` on this NAS. Each workspace gets its own
intermediate directory, so unrelated projects do not share a build lock.
No CPU, memory, job-count or optimization limits are configured.

The current Codex Rust workspace also sets both `build.target-dir` and
`build.build-dir` to `/vol2/1000/BuildCache/rust/codex-rs` in its local
`.cargo/config.toml`. Its existing `target` path is a compatibility symlink
to the SSD for scripts that execute `target/debug/...` directly.

The previous target contents were copied with timestamps preserved, then
moved out of the source tree into
`/vol1/1000/BuildCache/rust/codex-rs.before-ssd-20261013` as a migration
backup. They are not used for compilation. The source tree, Rust flags,
toolchain, download cache, credentials and running services stay in place.

For another Rust workspace, the user-level config moves intermediate
compilation and linking data to SSD automatically. Its final binaries keep
the project's existing output path unless that project also sets target-dir.

Migration validation on 2026-10-13: Cargo metadata reports both output
directories on vol2; the compatibility path resolves to the SSD filesystem.
The original Windows Rust flags are unchanged. Existing library tests for
`codex-utils-absolute-path` passed with the workspace-pinned Rust 1.95.0
and the default Rust 1.97.0. Compilation ran at normal priority with no
job-count limit. The old cache is retained outside the checkout.
