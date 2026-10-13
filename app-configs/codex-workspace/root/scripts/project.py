#!/usr/bin/env python3
"""按项目目录同步聚合 Git 与原仓库。"""

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    project["name"]: project
    for project in json.loads((ROOT / "projects.json").read_text())
}


def git(*args, capture=False):
    result = subprocess.run(
        ["git", *map(str, args)], cwd=ROOT, text=True, check=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def remote_url(project):
    if project["remote_url"]:
        return project["remote_url"]
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", capture=True))
    return str(common / "project-origins" / (project["name"] + ".git"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="查看项目目录与来源")
    commands.add_parser("remotes", help="按来源清单登记项目远端")
    pull = commands.add_parser("pull", help="拉取原项目并合入当前聚合分支")
    pull.add_argument("project", choices=PROJECTS)
    pull.add_argument("--branch", help="原项目分支，默认取来源清单")
    split = commands.add_parser("split", help="拆分当前 HEAD 中的项目提交")
    split.add_argument("project", choices=PROJECTS)
    split.add_argument("--branch", help="保存拆分结果的本机分支")
    push = commands.add_parser("push", help="推送项目提交到原仓库")
    push.add_argument("project", choices=PROJECTS)
    push.add_argument("branch", help="目标分支，例如 codex/update-favorites")
    checkout = commands.add_parser("checkout", help="导出独立项目 Git checkout")
    checkout.add_argument("project", choices=PROJECTS)
    checkout.add_argument("destination", type=Path)
    args = parser.parse_args()

    if args.command == "list":
        for name, project in PROJECTS.items():
            print(f"{name}\t{project['path']}\t{project['branch']}\t{remote_url(project)}")
    elif args.command == "remotes":
        for name, project in PROJECTS.items():
            git("config", f"remote.{name}.url", remote_url(project))
            git("config", "--replace-all", f"remote.{name}.fetch", f"+refs/heads/*:refs/remotes/{name}/*")
    else:
        project = PROJECTS[args.project]
        prefix = f"--prefix={project['path']}"
        if args.command == "pull":
            git("subtree", "pull", prefix, args.project, args.branch or project["branch"])
        elif args.command == "split":
            branch = ["--branch", args.branch] if args.branch else []
            git("subtree", "split", prefix, *branch)
        elif args.command == "push":
            git("subtree", "push", prefix, args.project, args.branch)
        elif args.command == "checkout":
            revision = git("subtree", "split", prefix, "--branch", f"export/{args.project}", capture=True)
            destination = args.destination.resolve()
            git("clone", "--no-checkout", ROOT, destination)
            git("-C", destination, "checkout", "--detach", revision)
            git("-C", destination, "remote", "set-url", "origin", remote_url(project))
            print(destination)


if __name__ == "__main__":
    main()
