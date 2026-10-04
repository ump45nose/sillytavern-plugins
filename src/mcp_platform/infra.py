"""共享设施的最小变更及比较后恢复。秘密不写入常规日志。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
import yaml
from dotenv import dotenv_values

from .manifest import private_write, template_yaml


def run(args, *, cwd=None, timeout=120, user=None):
    if user and os.geteuid() == 0:
        args = ["sudo", "-H", "-u", user, "--", *map(str, args)]
    result = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        # 工具可能回显秘密；命令输出仅写入受保护诊断文件，由上层负责。
        raise CommandFailure(args[0], result.stdout + result.stderr)
    return result.stdout


class CommandFailure(RuntimeError):
    def __init__(self, command, diagnostic):
        super().__init__(f"{Path(command).name} 执行失败；请查看私有诊断文件")
        self.diagnostic = diagnostic


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Journal:
    def __init__(self, path: Path, initial=None):
        self.path = path
        self.data = initial if initial is not None else json.loads(path.read_text())
        self.save()

    def save(self):
        private_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2))

    def set(self, **kwargs):
        self.data.update(kwargs)
        self.save()

    def replace_file(self, path: Path, text: str, *, expected_hash=None):
        before = path.read_text()
        before_hash = hashlib.sha256(before.encode()).hexdigest()
        if expected_hash is not None and before_hash != expected_hash:
            raise RuntimeError("共享文件在候选配置生成后发生外部修改")
        if before == text:
            return False
        entry = {"path": str(path), "before": before, "before_hash": before_hash,
                 "after_hash": hashlib.sha256(text.encode()).hexdigest(),
                 "mode": path.stat().st_mode & 0o777,
                 "uid": path.stat().st_uid, "gid": path.stat().st_gid}
        self.data.setdefault("files", []).append(entry)
        self.save()
        if digest(path) != entry["before_hash"]:
            raise RuntimeError("共享文件在写入前发生外部修改")
        private_write(path, text)
        os.chmod(path, entry["mode"])
        os.chown(path, entry["uid"], entry["gid"])
        return True

    def restore_files(self):
        restored = []
        for item in reversed(self.data.get("files", [])):
            path = Path(item["path"])
            current = digest(path)
            if current == item["before_hash"]:
                continue
            if current != item["after_hash"]:
                raise RuntimeError(f"共享文件存在外部修改，停止覆盖: {path}")
            private_write(path, item["before"])
            os.chmod(path, item["mode"])
            os.chown(path, item["uid"], item["gid"])
            restored.append(str(path))
        return restored


def authelia_text(original, app, env):
    parsed = template_yaml(original)
    oidc = parsed["identity_providers"]["oidc"]
    clients = oidc.get("clients", [])
    callback = app.public_url + "/auth/callback"
    existing = next((c for c in clients if c["client_id"] == app.auth.client_id), None)
    expected = {"redirect_uris": [callback], "authorization_policy": app.auth.authorization_policy,
                "claims_policy": app.auth.claims_policy,
                "scopes": app.auth.scopes, "token_endpoint_auth_method": "client_secret_basic",
                "require_pkce": True, "pkce_challenge_method": "S256"}
    if existing:
        if any(existing.get(k) != v for k, v in expected.items()):
            # 显式失败而不是借部署偷偷改变授权策略。
            raise ValueError("既有 Authelia 客户端配置与清单不一致，请显式协调后部署")
        return original
    if app.auth.authorization_policy not in oidc.get("authorization_policies", {}):
        raise ValueError("清单引用的 Authelia 授权策略不存在")
    if app.auth.claims_policy not in oidc.get("claims_policies", {}):
        raise ValueError("清单引用的 Authelia 身份声明策略不存在")
    secret = env[app.auth.secret_env]
    salt, iterations = os.urandom(16), 600000
    def encoded(b):
        return base64.b64encode(b).decode().rstrip("=").replace("+", ".")
    hashed = hashlib.pbkdf2_hmac("sha512", secret.encode(), salt, iterations)
    client = {"client_id": app.auth.client_id, "client_name": app.name,
              "client_secret": f"$pbkdf2-sha512${iterations}${encoded(salt)}${encoded(hashed)}",
              **expected, "grant_types": ["authorization_code", "refresh_token"],
              "response_types": ["code"]}
    tree = yaml.compose(re.sub(r"\{\{.*?\}\}", '"TEMPLATE_PLACEHOLDER"', original))

    def child(node, key):
        return next(v for k, v in node.value if k.value == key)

    node = child(child(child(tree, "identity_providers"), "oidc"), "clients")
    lines = original.splitlines(keepends=True)
    indent = node.value[0].start_mark.column - 2 if node.value else node.start_mark.column
    # 序列节点 start_mark 已指向 '-'；采用原首项所在行的实际缩进。
    if node.value:
        line = lines[node.value[0].start_mark.line]
        indent = len(line) - len(line.lstrip())
    addition = "".join(" " * indent + x + "\n" for x in
                       yaml.safe_dump([client], sort_keys=False, allow_unicode=True).splitlines())
    result = "".join(lines[:node.end_mark.line]) + "\n" + addition + "".join(lines[node.end_mark.line:])
    after = template_yaml(result)
    if after["identity_providers"]["oidc"]["clients"] != clients + [client]:
        raise ValueError("Authelia 候选配置未通过结构检查")
    return result


def tunnel_text(original, app):
    config = yaml.safe_load(original)
    rules = config["ingress"]
    origin = f"http://{app.bind_address}:{app.host_port}"
    existing = next((r for r in rules if r.get("hostname") == app.hostname), None)
    if existing:
        if existing.get("service") != origin:
            raise ValueError("已有同名 Tunnel 路由指向其他服务")
        return original
    rules.insert(len(rules) - 1, {"hostname": app.hostname, "service": origin})
    return yaml.safe_dump(config, sort_keys=False)


def ddns_text(original, hostname):
    config = yaml.safe_load(original)
    changed = False
    for provider in config.get("dnsconf", []):
        for family in ("ipv4", "ipv6"):
            section = provider.get(family, {})
            before = section.get("domains", [])
            after = [x for x in before if x.split("?", 1)[0] != hostname]
            if after != before:
                section["domains"] = after
                changed = True
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True) if changed else original


class Cloudflare:
    def __init__(self, target):
        env = dotenv_values(target.cloudflare_env)
        if env.get("CLOUDFLARE_API_TOKEN"):
            headers = {"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]}
        elif env.get("CLOUDFLARE_API_KEY") and env.get("CLOUDFLARE_EMAIL"):
            headers = {"X-Auth-Key": env["CLOUDFLARE_API_KEY"], "X-Auth-Email": env["CLOUDFLARE_EMAIL"]}
        else:
            raise ValueError("Cloudflare 凭据不完整")
        self.client = httpx.Client(base_url="https://api.cloudflare.com/client/v4/",
                                    headers=headers, timeout=20)
        self.zone = target.cloudflare_zone_id

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"Cloudflare API 返回非 JSON，HTTP {response.status_code}") from None
        if not response.is_success or not data.get("success"):
            codes = [e.get("code") for e in data.get("errors", [])]
            raise RuntimeError(f"Cloudflare API 失败 HTTP {response.status_code} codes={codes}")
        return data["result"]

    def find_zone(self, hostname):
        if not self.zone:
            labels = hostname.split(".")
            for offset in range(1, len(labels) - 1):
                found = self.request("GET", "zones", params={"name": ".".join(labels[offset:])})
                if found:
                    self.zone = found[0]["id"]
                    break
        if not self.zone:
            raise ValueError("无法定位 Cloudflare zone；请在目标配置指定 zone ID")
        return self.zone

    def records(self, hostname):
        return self.request("GET", f"zones/{self.zone}/dns_records", params={"name": hostname})

    @staticmethod
    def shape(records):
        keys = ("id", "type", "name", "content", "proxied", "ttl", "comment", "tags")
        return sorted([{k: r[k] for k in keys if k in r} for r in records], key=lambda x: x["id"])

    def switch(self, app, target, journal):
        self.find_zone(app.hostname)
        records = self.records(app.hostname)
        desired = target.tunnel_id + ".cfargotunnel.com"
        if len(records) == 1 and records[0]["type"] == "CNAME" and records[0]["content"] == desired and records[0].get("proxied"):
            return False
        if any(r["type"] not in {"A", "AAAA", "CNAME"} for r in records):
            raise ValueError("目标域名存在非地址记录，拒绝覆盖")
        journal.set(dns={"zone": self.zone, "hostname": app.hostname,
                         "before": self.shape(records), "after": self.shape(records)})
        for record in records:
            if self.shape(self.records(app.hostname)) != journal.data["dns"]["after"]:
                raise RuntimeError("DNS 在部署期间被其他程序修改")
            self.request("DELETE", f"zones/{self.zone}/dns_records/{record['id']}")
            journal.data["dns"]["after"] = self.shape(self.records(app.hostname))
            journal.save()
        if self.shape(self.records(app.hostname)) != journal.data["dns"]["after"]:
            raise RuntimeError("DNS 在部署期间被其他程序修改")
        self.request("POST", f"zones/{self.zone}/dns_records", json={
            "type": "CNAME", "name": app.hostname, "content": desired, "proxied": True, "ttl": 1,
        })
        journal.data["dns"]["after"] = self.shape(self.records(app.hostname))
        journal.save()
        return True

    def restore(self, state):
        self.zone = state["zone"]
        current = self.shape(self.records(state["hostname"]))
        if current != state["after"]:
            raise RuntimeError("DNS 存在外部修改，停止覆盖")
        for record in current:
            self.request("DELETE", f"zones/{self.zone}/dns_records/{record['id']}")
        for record in state["before"]:
            fields = {k: v for k, v in record.items() if k != "id"}
            self.request("POST", f"zones/{self.zone}/dns_records", json=fields)


def validate_authelia_candidate(target, text):
    """在运行容器的原环境校验副本，不改写生效配置。"""
    candidate = "/config/.mcp-platform-candidate-" + uuid4().hex + ".yml"
    with tempfile.TemporaryDirectory(prefix="mcp-platform-auth-") as directory:
        path = Path(directory) / "configuration.yml"
        private_write(path, text)
        run(["docker", "cp", path, target.authelia_container + ":" + candidate])
        try:
            run(["docker", "exec", "--user", "0", target.authelia_container,
                 "authelia", "config", "validate", "--config", candidate,
                 "--config.experimental.filters", "template"])
        finally:
            run(["docker", "exec", "--user", "0", target.authelia_container,
                 "rm", "-f", candidate])


def validate_tunnel_candidate(target, text):
    """用现有镜像与凭据目录校验独立候选文件。"""
    original = Path(target.tunnel_config)
    container = json.loads(run(["docker", "inspect", target.tunnel_container]))[0]
    candidate = original.parent / (".mcp-platform-candidate-" + uuid4().hex + ".yml")
    try:
        private_write(candidate, text)
        os.chown(candidate, original.stat().st_uid, original.stat().st_gid)
        run(["docker", "run", "--rm", "--network", "host",
             "--user", container["Config"].get("User") or "0",
             "--mount", f"type=bind,source={original.parent},target=/etc/cloudflared,readonly",
             container["Image"], "tunnel", "--config", "/etc/cloudflared/" + candidate.name,
             "ingress", "validate"])
    finally:
        candidate.unlink(missing_ok=True)


def restart_authelia(target):
    run(["docker", "exec", target.authelia_container, "authelia", "config", "validate",
         "--config", "/config/configuration.yml", "--config.experimental.filters", "template"])
    run(["docker", "restart", target.authelia_container])


def switch_tunnel(target):
    """同 Tunnel 的临时副本先连通，再更新主容器并撤下临时副本。"""
    c = json.loads(run(["docker", "inspect", target.tunnel_container]))[0]
    name = target.tunnel_container + "-platform-candidate"
    run(["docker", "run", "--rm", "--network", "host",
         "--user", c["Config"].get("User") or "0",
         "--mount", f"type=bind,source={Path(target.tunnel_config).parent},target=/etc/cloudflared,readonly",
         c["Image"], "tunnel", "--config", "/etc/cloudflared/config.yml", "ingress", "validate"])
    run(["docker", "run", "-d", "--name", name, "--network", "host",
         "--user", c["Config"].get("User") or "0",
         "--mount", f"type=bind,source={Path(target.tunnel_config).parent},target=/etc/cloudflared,readonly",
         c["Image"], *c["Config"]["Cmd"]])
    try:
        for _ in range(20):
            log = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
            if "Registered tunnel connection" in log.stdout + log.stderr:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Tunnel 副本未建立连接")
        run(["docker", "restart", target.tunnel_container])
        started_at = run(["docker", "inspect", target.tunnel_container, "--format", "{{.State.StartedAt}}"] ).strip()
        for _ in range(20):
            result = subprocess.run(["docker", "logs", "--since", started_at, target.tunnel_container],
                                    capture_output=True, text=True)
            if "Registered tunnel connection" in result.stdout + result.stderr:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Tunnel 主容器未恢复连接")
    finally:
        run(["docker", "rm", "-f", name])
