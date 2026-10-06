#!/usr/bin/env python3
"""Keep hermes and yuwk read-write access to the Hermes runtime tree.

POSIX default ACLs are intersected with the mode requested at file creation and
can also be masked by a later chmod.  This reconciler applies the intended ACL
once at startup and then repairs create, move, write, and attribute events with
inotify.  Access is granted explicitly to the runtime owner and the local
administrator; this does not make files accessible to other local users.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import logging
import os
from pathlib import Path
import select
import stat
import struct
import subprocess
import sys
import time


ROOT = Path("/home/hermes/.hermes")
HOME = Path("/home/hermes")
ACCESS_USERS = ("hermes", "yuwk")

IN_ATTRIB = 0x00000004
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
WATCH_MASK = (
    IN_ATTRIB
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)
EVENT = struct.Struct("iIII")
BATCH_SIZE = 256

LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.inotify_init1.argtypes = [ctypes.c_int]
LIBC.inotify_init1.restype = ctypes.c_int
LIBC.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
LIBC.inotify_add_watch.restype = ctypes.c_int


def run_setfacl(paths: list[Path], acl: str) -> None:
    for offset in range(0, len(paths), BATCH_SIZE):
        batch = paths[offset : offset + BATCH_SIZE]
        result = subprocess.run(
            ["/usr/bin/setfacl", "-P", "-m", acl, "--", *(os.fspath(path) for path in batch)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode:
            errors = [
                line
                for line in result.stderr.splitlines()
                if line and "No such file or directory" not in line
            ]
            if errors:
                logging.error("setfacl failed rc=%s: %s", result.returncode, "\n".join(errors))


DIR_ACL = (
    "u::rwx,"
    + ",".join(f"u:{user}:rwx" for user in ACCESS_USERS)
    + ",m::rwx,d:u::rwx,"
    + ",".join(f"d:u:{user}:rwx" for user in ACCESS_USERS)
    + ",d:m::rwx"
)
FILE_READ_ACL = (
    "u::rw-,"
    + ",".join(f"u:{user}:rw-" for user in ACCESS_USERS)
    + ",m::rw-"
)
FILE_EXEC_ACL = (
    "u::rwx,"
    + ",".join(f"u:{user}:rwx" for user in ACCESS_USERS)
    + ",m::rwx"
)
HOME_ACL = DIR_ACL


def reconcile_home() -> None:
    run_setfacl([HOME], HOME_ACL)


def collect_tree(start: Path) -> tuple[list[Path], list[Path], list[Path]]:
    directories: list[Path] = []
    regular_files: list[Path] = []
    executable_files: list[Path] = []

    if start.is_file():
        mode = start.stat().st_mode
        target = executable_files if mode & 0o111 else regular_files
        target.append(start)
        return directories, regular_files, executable_files

    for directory, child_dirs, files in os.walk(start, topdown=True, followlinks=False):
        current = Path(directory)
        directories.append(current)

        child_dirs[:] = [name for name in child_dirs if not (current / name).is_symlink()]

        for file_name in files:
            path = current / file_name
            if path.is_symlink():
                continue
            try:
                mode = path.stat().st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(mode):
                continue
            target = executable_files if mode & 0o111 else regular_files
            target.append(path)

    return directories, regular_files, executable_files


def reconcile_tree(start: Path = ROOT) -> tuple[int, int]:
    directories, regular_files, executable_files = collect_tree(start)
    run_setfacl(directories, DIR_ACL)
    run_setfacl(regular_files, FILE_READ_ACL)
    run_setfacl(executable_files, FILE_EXEC_ACL)
    return len(directories), len(regular_files) + len(executable_files)


def has_expected_acl(path: Path, is_directory: bool, executable: bool = False) -> bool:
    result = subprocess.run(
        ["/usr/bin/getfacl", "-P", "-c", "--", os.fspath(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode:
        return False
    entries = {line.split("\t", 1)[0] for line in result.stdout.splitlines() if line}
    permission = "rwx" if is_directory or executable else "rw-"
    required = {
        *(f"user:{user}:{permission}" for user in ACCESS_USERS),
        f"mask::{permission}",
    }
    if is_directory:
        required.update(
            {
                *(f"default:user:{user}:rwx" for user in ACCESS_USERS),
                "default:mask::rwx",
            }
        )
    return required.issubset(entries)


def reconcile_path(path: Path, is_directory: bool | None = None) -> None:
    if path.is_symlink() or not path.exists():
        return
    if is_directory is None:
        is_directory = path.is_dir()
    if is_directory:
        if not has_expected_acl(path, is_directory=True):
            run_setfacl([path], DIR_ACL)
        return
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISREG(mode):
        executable = bool(mode & 0o111)
        if not has_expected_acl(path, is_directory=False, executable=executable):
            run_setfacl([path], FILE_EXEC_ACL if executable else FILE_READ_ACL)


class Inotify:
    def __init__(self) -> None:
        self.fd = LIBC.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        self.by_watch: dict[int, Path] = {}
        self.by_path: dict[Path, int] = {}

    def add(self, path: Path) -> None:
        if path in self.by_path:
            return
        watch = LIBC.inotify_add_watch(self.fd, os.fsencode(path), WATCH_MASK)
        if watch < 0:
            error = ctypes.get_errno()
            if error not in {errno.ENOENT, errno.ENOTDIR, errno.EACCES}:
                logging.warning("cannot watch %s: %s", path, os.strerror(error))
            return
        old_path = self.by_watch.get(watch)
        if old_path is not None:
            self.by_path.pop(old_path, None)
        self.by_watch[watch] = path
        self.by_path[path] = watch

    def add_tree(self, start: Path) -> None:
        for directory, child_dirs, _ in os.walk(start, topdown=True, followlinks=False):
            current = Path(directory)
            self.add(current)
            child_dirs[:] = [
                name
                for name in child_dirs
                if not (current / name).is_symlink()
            ]

    def remove_mapping(self, watch: int) -> None:
        path = self.by_watch.pop(watch, None)
        if path is not None:
            self.by_path.pop(path, None)

    def read(self) -> bytes:
        try:
            return os.read(self.fd, 1024 * 1024)
        except BlockingIOError:
            return b""


def daemon(ready_file: Path | None) -> int:
    watcher = Inotify()
    # Install watches before the initial reconciliation so concurrent writers
    # cannot re-apply restrictive modes in the startup window unnoticed.
    watcher.add_tree(ROOT)
    reconcile_home()
    directories, files = reconcile_tree(ROOT)
    # Pick up directories created while the first traversal was in progress.
    watcher.add_tree(ROOT)
    logging.info(
        "initial reconcile complete: directories=%s files=%s watches=%s",
        directories,
        files,
        len(watcher.by_watch),
    )
    if ready_file is not None:
        ready_file.write_text(
            f"ready_at={time.time():.6f}\nwatches={len(watcher.by_watch)}\n",
            encoding="utf-8",
        )

    poller = select.poll()
    poller.register(watcher.fd, select.POLLIN)

    while True:
        poller.poll(1000)
        data = watcher.read()
        offset = 0
        while offset + EVENT.size <= len(data):
            watch, mask, _cookie, name_length = EVENT.unpack_from(data, offset)
            offset += EVENT.size
            name_bytes = data[offset : offset + name_length]
            offset += name_length
            name = name_bytes.rstrip(b"\0")

            if mask & IN_Q_OVERFLOW:
                logging.warning("inotify queue overflow; running full reconciliation")
                reconcile_tree(ROOT)
                watcher.add_tree(ROOT)
                continue
            if mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED):
                watcher.remove_mapping(watch)
                continue

            base = watcher.by_watch.get(watch)
            if base is None:
                continue
            path = base / os.fsdecode(name) if name else base

            is_directory = bool(mask & IN_ISDIR)
            if is_directory and mask & (IN_CREATE | IN_MOVED_TO):
                reconcile_tree(path)
                watcher.add_tree(path)
            else:
                reconcile_path(path, is_directory=is_directory)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--daemon", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if os.geteuid() != 0:
        logging.error("must run as root")
        return 2
    if not ROOT.is_dir():
        logging.error("Hermes root does not exist: %s", ROOT)
        return 2
    if args.once:
        reconcile_home()
        directories, files = reconcile_tree(ROOT)
        logging.info(
            "reconcile complete: directories=%s files=%s",
            directories,
            files,
        )
        return 0
    return daemon(args.ready_file)


if __name__ == "__main__":
    sys.exit(main())
