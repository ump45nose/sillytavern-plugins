"""首次从旧 Compose 迁移；日后使用 mcpctl deploy，不重复导入旧数据。"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mcp_platform.deploy import (
    build_bundle, compose_args, compose_text, deployment_lock, prepare_env,
)
from mcp_platform.exposure import probe_existing, wait_public_probe
from mcp_platform.infra import (
    Cloudflare, Journal, authelia_text, ddns_text, digest, restart_authelia, run,
    switch_tunnel, tunnel_text, validate_authelia_candidate, validate_tunnel_candidate,
)
from mcp_platform.manifest import load_app, load_target, private_write


def remove_service(text, name):
    tree = yaml.compose(text)
    services = next(v for k, v in tree.value if k.value == "services")
    key, value = next((k, v) for k, v in services.value if k.value == name)
    lines = text.splitlines(keepends=True)
    result = "".join(lines[:key.start_mark.line] + lines[value.end_mark.line:])
    before = yaml.safe_load(text)
    del before["services"][name]
    if yaml.safe_load(result) != before:
        raise ValueError("旧 Compose 服务移除候选不一致")
    return result


def snapshot(source, destination):
    destination.mkdir(mode=0o700)
    for p in source.rglob("*"):
        if p.is_symlink():
            raise ValueError("邮件目录包含符号链接，拒绝复制")
        relative = p.relative_to(source)
        if relative.parent == Path(".") and p.name.startswith("catalog.sqlite3"):
            continue
        target = destination / relative
        if p.is_dir():
            target.mkdir(mode=0o700, exist_ok=True)
        elif p.is_file():
            shutil.copyfile(p, target)
            target.chmod(0o600)
    with sqlite3.connect(f"file:{source / 'catalog.sqlite3'}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination / "catalog.sqlite3") as dst:
            src.backup(dst)
    for p in [destination, *destination.rglob("*")]:
        p.chmod(0o700 if p.is_dir() else 0o600)
        os.chown(p, 1000, 1001)


def baseline(data):
    with sqlite3.connect(f"file:{data / 'catalog.sqlite3'}?mode=ro", uri=True) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if r[0] != "schema_metadata"]
        result = {}
        for table in tables:
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            rows = sorted(repr(row) for row in db.execute(f'SELECT * FROM "{table}"'))
            result[table] = (columns, hashlib.sha256(repr(rows).encode()).hexdigest())
        return result


def verify_preserved(data, before):
    with sqlite3.connect(f"file:{data / 'catalog.sqlite3'}?mode=ro", uri=True) as db:
        assert db.execute("SELECT version FROM schema_metadata").fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM managed_account").fetchone()[0] == 4
        for table, (columns, expected) in before.items():
            select = ",".join('"' + c + '"' for c in columns)
            rows = sorted(repr(row) for row in db.execute(f'SELECT {select} FROM "{table}"'))
            if hashlib.sha256(repr(rows).encode()).hexdigest() != expected:
                raise ValueError("上游迁移改变原配置行: " + table)


def migrate_copy(image, data, release):
    before = baseline(data)
    bootstrap = data / ".config/mcp-email-server/config.bootstrap.toml"
    bootstrap_hash = digest(bootstrap)
    command = ["docker", "run", "--rm", "--user", "1000:1001", "--workdir", "/data",
               "--mount", f"type=bind,src={data},dst=/data", "--env", "HOME=/data",
               "--env", "XDG_CONFIG_HOME=/data/.config", image,
               "mcp-email-server", "config", "doctor", "--json"]
    result = run(command)
    private_write(release / (data.name + "-doctor.json"), result)
    report = json.loads(result)
    if not report.get("ok") or report["data"].get("problems"):
        raise ValueError("邮件配置升级预检失败")
    verify_preserved(data, before)
    if digest(bootstrap) != bootstrap_hash:
        raise ValueError("上游迁移修改了 bootstrap 选择")


def bridge_smoke(image, data, release):
    code = '''import asyncio,json,jsonref
from fastmcp import Client
from mcp_platform import RuntimeConfig
from email_mcp_platform.server import create_app
from mcp_email_server.app import mcp
def normalized(value):
    if value is None:return None
    value=jsonref.replace_refs(value,proxies=False)
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if k not in ["$defs","definitions"]}
        if isinstance(v,list):return [clean(x) for x in v]
        return v
    return clean(value)
async def smoke():
    _,server,_=create_app(RuntimeConfig(name="email-smoke",development_no_auth=True,audit_enabled=False))
    async with Client(mcp) as original:
        expected={t.name:t.model_dump() for t in await original.list_tools()}
    async with Client(server) as wrapped:
        actual={t.name:t.model_dump() for t in await wrapped.list_tools()}
        assert set(actual)==set(expected)
        for name in expected:
            for key in ["name","description","annotations","inputSchema","outputSchema"]:
                assert normalized(actual[name][key])==normalized(expected[name][key]),(name,key)
        accounts=await wrapped.call_tool("list_available_accounts",{})
        assert not accounts.is_error
        print(json.dumps({"tools":len(actual),"schemas_preserved":True,"account_discovery":True}))
asyncio.run(smoke())'''
    result = run(["docker", "run", "--rm", "--user", "1000:1001", "--workdir", "/data",
        "--mount", f"type=bind,src={data},dst=/data", "--env", "HOME=/data",
        "--env", "XDG_CONFIG_HOME=/data/.config", image, "python", "-c", code])
    private_write(release / "bridge-smoke.json", result)


def main(prepared_release=None):
    if os.geteuid() != 0:
        raise PermissionError("首次迁移需 sudo -n；秘密不写入输出")
    source = Path(__file__).resolve().parent
    targets = Path("/home/yuwk/.config/mcp-platform/targets.yaml")
    target = load_target(targets, "nas")
    app = load_app(source)
    root = Path(target.runtime_root) / app.id
    if (root / "current.json").exists():
        raise ValueError("服务已迁移；请使用 mcpctl deploy，拒绝重新复制旧库")
    with deployment_lock(target):
        release = root / "releases" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        release.mkdir(parents=True, mode=0o700)
        for p in (root.parent, root, root / "releases", release):
            os.chown(p, 1000, 1001)
        journal = Journal(release / "journal.json", {"app": app.id, "status": "preparing",
                           "migration": "tool-to-mcp-platform", "files": []})
        cf = None
        stopped = False
        new_started = False
        stable = Path(target.compose_files[app.id])
        try:
            old = json.loads(run(["docker", "inspect", "email-mcp"]))[0]
            private_write(release / "old-container.json", json.dumps(old))
            if not old["State"]["Running"]:
                raise ValueError("旧服务不在运行，停止猜测迁移状态")
            old_compose = Path(old["Config"]["Labels"]["com.docker.compose.project.config_files"])
            old_text = old_compose.read_text()
            removed = remove_service(old_text, "email-mcp")
            old_data = Path(next(m["Source"] for m in old["Mounts"] if m["Destination"] == "/data"))
            env_path, env = prepare_env(app, target)
            original_env = dict(e.split("=", 1) for e in old["Config"]["Env"])
            for key in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "TZ"]:
                if key in original_env:
                    env[key] = original_env[key]
            private_write(env_path, "".join(k + "=" + json.dumps(v) + "\n" for k, v in env.items()))
            auth_original = Path(target.authelia_config).read_text()
            tunnel_original = Path(target.tunnel_config).read_text()
            ddns_original = Path(target.ddns_config).read_text()
            auth_candidate = authelia_text(auth_original, app, env)
            tunnel_candidate = tunnel_text(tunnel_original, app)
            ddns_candidate = ddns_text(ddns_original, app.hostname)
            cf = Cloudflare(target)
            cf.find_zone(app.hostname)
            dns_before = cf.records(app.hostname)
            if dns_before:
                raise ValueError("邮件域名已有 DNS 记录，拒绝覆盖")
            validate_authelia_candidate(target, auth_candidate)
            validate_tunnel_candidate(target, tunnel_candidate)
            if prepared_release:
                prepared = Path(prepared_release).resolve()
                if not prepared.is_relative_to((root / "releases").resolve()):
                    raise ValueError("预构建记录必须在该应用的私有 releases 目录内")
                prior = json.loads((prepared / "journal.json").read_text())
                if prior.get("status") != "failed" or prior.get("rollback_status") != "complete":
                    raise ValueError("只能复用已安全回滚的准备记录")
                source_sha, core_sha, image = prior["source_sha"], prior["core_sha"], prior["image"]
                changed = run(["git", "diff", source_sha, "HEAD", "--", "src", "pyproject.toml",
                               "uv.lock", "mcp.app.yaml"], cwd=source, user=target.build_user)
                if changed.strip():
                    raise ValueError("运行代码或锁文件已变化，必须重新构建")
                run(["docker", "image", "inspect", image])
                private_write(release / "build-artifacts.json", (prepared / "build/artifacts.json").read_text())
                journal.set(prepared_release=str(prepared))
            else:
                image, source_sha, core_sha = build_bundle(app, source, target, release / "build")
            journal.set(runner_sha=run(["git", "rev-parse", "HEAD"], cwd=source,
                                      user=target.build_user).strip())
            journal.set(image=image, source_sha=source_sha, core_sha=core_sha)
            trial = release / "trial-data"
            snapshot(old_data, trial)
            migrate_copy(image, trial, release)
            bridge_smoke(image, trial, release)
            print("镜像及四账号升级副本检查通过；进入容器切换", flush=True)
            # 精确检查共享库使用者，不允许仍有 UI/CLI 与升级后的副本交叉使用。
            processes = run(["docker", "top", "email-mcp", "-eo", "comm"]).splitlines()[1:]
            if len(processes) != 2 or not any("mcp-email" in p for p in processes):
                raise ValueError("旧容器存在额外进程；需核对目录使用者")
            if digest(old_compose) != hashlib.sha256(old_text.encode()).hexdigest():
                raise ValueError("旧 Compose 在准备期间发生外部修改")
            run(["docker", "stop", "--time", "30", "email-mcp"])
            stopped = True
            data = root / "data"
            if data.exists():
                raise ValueError("平台数据目录已存在，拒绝覆盖")
            snapshot(old_data, data)
            migrate_copy(image, data, release)
            oauth = root / "oauth"
            oauth.mkdir(mode=0o700)
            os.chown(oauth, 1000, 1001)
            for name, path in [("email-mcp-data", data), ("email-mcp-oauth", oauth)]:
                if name in run(["docker", "volume", "ls", "--format", "{{.Name}}"] ).split():
                    raise ValueError("邮件卷已存在，拒绝重新绑定")
                run(["docker", "volume", "create", "--driver", "local", "--opt", "type=none",
                     "--opt", "o=bind", "--opt", f"device={path}", name])
            if not stable.exists():
                private_write(stable, "services: {}\n")
            compose_original = stable.read_text()
            compose = compose_text(app, image, env_path, compose_original)
            candidate = release / "compose.yaml"
            private_write(candidate, compose)
            run([*compose_args(app, candidate), "config", "--quiet"])
            journal.set(compose=str(stable), original_data=str(old_data), data=str(data),
                        previous={"image": old["Image"], "container": old["Id"]})
            if journal.replace_file(Path(target.authelia_config), auth_candidate,
                    expected_hash=hashlib.sha256(auth_original.encode()).hexdigest()):
                restart_authelia(target)
            journal.replace_file(stable, compose,
                    expected_hash=hashlib.sha256(compose_original.encode()).hexdigest())
            new_started = True
            run([*compose_args(app, stable), "up", "-d", "--no-deps", app.compose_service])
            from mcp_platform.deploy import wait_health
            wait_health(app)
            probe_existing(app, target)
            journal.replace_file(old_compose, removed,
                    expected_hash=hashlib.sha256(old_text.encode()).hexdigest())
            if journal.replace_file(Path(target.tunnel_config), tunnel_candidate,
                    expected_hash=hashlib.sha256(tunnel_original.encode()).hexdigest()):
                switch_tunnel(target)
            if journal.replace_file(Path(target.ddns_config), ddns_candidate,
                    expected_hash=hashlib.sha256(ddns_original.encode()).hexdigest()):
                run(["docker", "restart", target.ddns_container])
            if cf.records(app.hostname) != dns_before:
                raise ValueError("DNS 在准备期间发生外部修改")
            cf.switch(app, target, journal)
            wait_public_probe(app, target)
            from mcp_platform.deploy import container_for
            image_id = json.loads(run(["docker", "inspect", container_for(app)]))[0]["Image"]
            env_fingerprint = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
            journal.set(status="complete", image_id=image_id, env_fingerprint=env_fingerprint)
            state = {k: journal.data[k] for k in ["source_sha", "core_sha", "image", "image_id", "compose", "env_fingerprint"]}
            state["journal"] = str(journal.path)
            private_write(root / "current.json", json.dumps(state, indent=2))
            print("邮件容器迁移及 Tunnel 接入完成；私有记录: " + str(journal.path), flush=True)
        except Exception as error:
            private_write(release / "error.log", getattr(error, "diagnostic", str(error)))
            journal.set(status="failed")
            try:
                if new_started:
                    run([*compose_args(app, stable), "rm", "--stop", "--force", app.compose_service])
                if journal.data.get("dns"):
                    cf.restore(journal.data["dns"])
                restored = journal.restore_files()
                if target.tunnel_config in restored:
                    switch_tunnel(target)
                if target.authelia_config in restored:
                    restart_authelia(target)
                if target.ddns_config in restored:
                    run(["docker", "restart", target.ddns_container])
                if stopped:
                    run(["docker", "start", "email-mcp"])
                journal.set(rollback_status="complete")
            except Exception as rollback_error:
                private_write(release / "rollback-error.log", getattr(rollback_error, "diagnostic", str(rollback_error)))
                journal.set(rollback_status="needs_attention")
            raise RuntimeError("迁移未完成；查看私有记录: " + str(journal.path)) from None
        finally:
            if cf:
                cf.client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="邮件服务首次迁移；不重导入现有平台数据")
    parser.add_argument("--prepared-release", help="复用安全回滚后的构建，运行输入必须未改变")
    main(parser.parse_args().prepared_release)
