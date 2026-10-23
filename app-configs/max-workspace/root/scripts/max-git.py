#!/usr/bin/env python3
"""Max 跨仓任务：建立工作副本，查看差异，按仓提交、合并与清理。"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args, capture=False, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def read(repo, *args):
    return git(repo, *args, capture=True).stdout.rstrip("\n")


def stop(message):
    sys.exit(message)


def common_dir():
    return Path(read(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def projects():
    lines = read(ROOT, "config", "-f", str(ROOT / ".gitmodules"),
                 "--get-regexp", r"^submodule\..*\.path$")
    return [line.split(" ", 1)[1] for line in lines.splitlines()]


def task_path(root):
    key = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return common_dir() / "max-tasks" / f"{key}.json"


def save(task):
    path = task_path(Path(task["root"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n")


def current_task():
    path = task_path(ROOT)
    return json.loads(path.read_text()) if path.exists() else None


def require_task():
    task = current_task()
    if task is None or not task["active"]:
        stop("请在已初始化的 Max 任务目录内执行此操作。")
    return task


def selected(args, task):
    names = args.repos or (list(task["repos"]) if task else projects())
    if task:
        for name in names:
            if name not in task["repos"]:
                stop(f"{name} 尚未加入任务，先执行 setup {name}。")
    return names


def attach(task, names):
    target = Path(task["root"])
    primary = common_dir().parent
    for name in names:
        if name in task["repos"]:
            entry = task["repos"][name]
            if (target / name / ".git").exists():
                continue
            git(entry["source"], "worktree", "add", str(target / name), task["branch"])
        else:
            source = primary / name
            entry = {
                "source": str(source),
                "base": read(source, "rev-parse", "HEAD"),
                "target_branch": read(source, "branch", "--show-current"),
            }
            if read(source, "status", "--porcelain"):
                print(f"{name}: 原目录的未提交改动保留，新任务从 HEAD 启动。", flush=True)
            git(source, "worktree", "add", "-b", task["branch"],
                str(target / name), entry["base"])
            task["repos"][name] = entry
        task["active"] = True
        save(task)
    print(f"任务目录：{target}", flush=True)
    print(f"子仓分支：{task['branch']}", flush=True)


def start(args):
    primary = common_dir().parent
    if ROOT != primary:
        stop("start 从 Max 主工作区执行；Codex 创建的 worktree 使用 setup。")
    branch = f"codex/max/{args.name}"
    git(ROOT, "check-ref-format", "--branch", branch, capture=True)
    target = primary / ".worktrees" / args.name
    target.parent.mkdir(exist_ok=True)
    git(ROOT, "worktree", "add", "-b", branch, str(target), "HEAD")
    task = {"root": str(target), "name": args.name, "branch": branch,
            "owned_parent": True, "active": True, "repos": {}}
    save(task)
    attach(task, args.repos or projects())


def setup(args):
    if ROOT == common_dir().parent:
        print("当前是 Max 主工作区；使用 start 创建任务，或在 Codex 中选择 Worktree。")
        return
    task = current_task()
    if task is None:
        key = task_path(ROOT).stem
        task = {"root": str(ROOT), "name": key, "branch": f"codex/max/{key}",
                "owned_parent": False, "active": True, "repos": {}}
        save(task)
    attach(task, args.repos or projects())


def status(args):
    task = current_task()
    print(f"Max: {ROOT}", flush=True)
    print("父仓 worktrees：", flush=True)
    git(ROOT, "worktree", "list")
    if task:
        print(f"任务：{task['name']}，{'运行中' if task['active'] else '已清理'}", flush=True)
        if not task["active"]:
            return
    else:
        directory = common_dir() / "max-tasks"
        for path in sorted(directory.glob("*.json")):
            item = json.loads(path.read_text())
            if item["active"]:
                print(f"任务 {item['name']}: {item['root']}", flush=True)
    for name in selected(args, task):
        repo = ROOT / name
        branch = read(repo, "branch", "--show-current") or "detached HEAD"
        head = read(repo, "rev-parse", "--short", "HEAD")
        print(f"\n=== {name} | {branch} | {head} ===", flush=True)
        git(repo, "worktree", "list")
        if task:
            count = read(repo, "rev-list", "--count", f"{task['repos'][name]['base']}..HEAD")
            print(f"任务提交：{count}", flush=True)
        print(read(repo, "status", "--short") or "工作区干净", flush=True)


def diff(args):
    task = current_task()
    if task and not task["active"]:
        stop("任务工作副本已清理，提交保留在各子仓任务分支。")
    for name in selected(args, task):
        repo = ROOT / name
        base = task["repos"][name]["base"] if task else "HEAD"
        print(f"\n=== {name} | 相对 {base[:12]} ===", flush=True)
        git(repo, "--no-pager", "diff", "--binary", base, "--")
        files = read(repo, "ls-files", "--others", "--exclude-standard", "-z")
        for file in files.split("\0"):
            if file:
                result = git(repo, "--no-pager", "diff", "--no-index", "--binary",
                             "--", "/dev/null", file, check=False)
                if result.returncode not in (0, 1):
                    sys.exit(result.returncode)


def commit(args):
    task = require_task()
    for name in selected(args, task):
        repo = ROOT / name
        if read(repo, "status", "--porcelain"):
            git(repo, "add", "--all")
            git(repo, "commit", "-m", args.message)
        else:
            print(f"{name}: 没有待提交文件。", flush=True)


def ancestor(repo, before, after):
    result = git(repo, "merge-base", "--is-ancestor", before, after, check=False)
    if result.returncode not in (0, 1):
        sys.exit(result.returncode)
    return result.returncode == 0


def merge(args):
    task = require_task()
    pending = []
    for name in selected(args, task):
        entry = task["repos"][name]
        source = Path(entry["source"])
        if read(ROOT / name, "status", "--porcelain"):
            stop(f"{name}: 任务有未提交改动，先执行 commit。")
        if entry["target_branch"] and ancestor(source, task["branch"],
                                               f"refs/heads/{entry['target_branch']}"):
            continue
        if read(source, "status", "--porcelain"):
            stop(f"{name}: 原工作区有未提交改动，整理后再合并。")
        if not entry["target_branch"] or read(source, "branch", "--show-current") != entry["target_branch"]:
            stop(f"{name}: 原工作区需切回任务启动时的分支 {entry['target_branch']}。")
        if not ancestor(source, "HEAD", task["branch"]):
            stop(f"{name}: 原分支已有其他提交，请先处理分支分歧。")
        pending.append(source)
    for source in pending:
        git(source, "merge", "--ff-only", task["branch"])
    print("所选子仓的任务提交已合并。", flush=True)


def release(task):
    # 先检查整个任务，再移除子仓工作副本；任务分支始终保留。
    for name in task["repos"]:
        if read(ROOT / name, "status", "--porcelain"):
            stop(f"{name}: 有未提交改动，先提交后再清理。")
    for name, entry in task["repos"].items():
        git(entry["source"], "worktree", "remove", str(ROOT / name))
    task["active"] = False
    save(task)
    print(f"子仓工作副本已清理，提交保留在分支 {task['branch']}。", flush=True)


def cleanup(args):
    task = current_task()
    if task is None or not task["active"]:
        return
    release(task)


def clean(args):
    task = require_task()
    for name, entry in task["repos"].items():
        if not entry["target_branch"] or not ancestor(entry["source"], task["branch"],
                                                      f"refs/heads/{entry['target_branch']}"):
            stop(f"{name}: 任务提交尚未合并，保留任务工作副本。")
    if read(ROOT, "status", "--porcelain", "--ignore-submodules=all"):
        stop("Max 父仓有未提交文件，先整理后再清理。")
    release(task)
    if task["owned_parent"]:
        primary = common_dir().parent
        git(primary, "worktree", "remove", "--force", str(ROOT))
        print("Max 任务工作副本已清理。", flush=True)
    else:
        print("父仓 worktree 由 Codex 管理。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("start", "创建 Max 任务 worktree"), ("setup", "初始化 Codex worktree 的子仓"),
        ("status", "查看各仓状态和任务"), ("diff", "查看完整跨仓差异"),
        ("commit", "按仓提交任务改动"), ("merge", "快进合并到原开发分支"),
    ]:
        command = commands.add_parser(name, help=help_text)
        if name == "start":
            command.add_argument("name", help="任务名")
        if name == "commit":
            command.add_argument("-m", "--message", required=True)
        command.add_argument("repos", nargs="*", choices=projects(), metavar="REPO")
    commands.add_parser("clean", help="合并后清理任务工作副本，保留分支")
    commands.add_parser("cleanup", help="Codex 清理钩子：移除干净的子仓工作副本，保留分支")
    args = parser.parse_args()
    handlers = {"start": start, "setup": setup, "status": status, "diff": diff,
                "commit": commit, "merge": merge, "clean": clean, "cleanup": cleanup}
    handlers[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
