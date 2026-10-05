"""中文 CLI：初始化、预检、部署、回滚和保持身份的插件打包。"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
import zipfile
from importlib.metadata import version
from pathlib import Path

import yaml

from .auth_deploy import deploy_auth_only, prepare_auth_change
from .deploy import (
    deploy,
    deployment_lock,
    rollback_journal,
)
from .exposure import deploy_existing
from .infra import Cloudflare, Journal, run, tunnel_text
from .manifest import AppManifest, load_app, load_target, private_write


def default_targets():
    owner = os.getenv("SUDO_USER")
    home = Path(pwd.getpwnam(owner).pw_dir) if owner else Path.home()
    return home / ".config/mcp-platform/targets.yaml"


def resolve_source(app_id, target, explicit):
    if explicit:
        return explicit.resolve()
    if app_id in target.source_roots:
        return Path(target.source_roots[app_id])
    catalog = Path(target.platform_repo) / "apps" / (app_id + ".yaml")
    if not catalog.is_file():
        raise ValueError("应用未登记；请使用 --source 或在 apps 目录登记仓库和提交")
    entry = yaml.safe_load(catalog.read_text())
    revision = entry["revision"]
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("应用目录必须锁定完整 Git 提交")
    owner = pwd.getpwnam(target.build_user)
    cache = Path(owner.pw_dir) / ".cache/mcp-platform/sources" / app_id
    cache.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        for path in (cache.parent.parent, cache.parent, cache):
            os.chown(path, owner.pw_uid, owner.pw_gid)
    destination = cache / revision
    if not destination.exists():
        run(["git", "clone", "--no-checkout", entry["repository"], destination], user=target.build_user)
        run(["git", "checkout", "--detach", revision], cwd=destination, user=target.build_user)
    source = (destination / entry.get("path", ".")).resolve()
    if not source.is_relative_to(destination.resolve()):
        raise ValueError("清单子目录不能离开业务仓库")
    return source


def init_project(name, destination):
    import re
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", name):
        raise ValueError("项目名使用小写字母、数字和连字符")
    if destination.exists():
        raise ValueError("目标目录已存在，拒绝覆盖")
    module = name.replace("-", "_")
    source = destination / "src" / module
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "server.py").write_text(f'''from dotenv import load_dotenv
from mcp_platform import RuntimeConfig, authorize, create_server, create_http_app
import uvicorn

def create_app():
    load_dotenv()
    config = RuntimeConfig.from_env("{name}")
    server = create_server(config, healthcheck=lambda: {{"status": "ok"}})

    @server.tool(auth=authorize("read", config), annotations={{"readOnlyHint": True}})
    def hello(name: str = "world") -> dict:
        """返回问候，用于验证新服务。"""
        return {{"message": "hello " + name}}

    return create_http_app(server, config), config

def main():
    app, config = create_app()
    uvicorn.run(app, host=config.host, port=config.port)
''')
    (destination / "pyproject.toml").write_text(f'''[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["mcp-platform==0.1.3"]

[project.scripts]
{name}-server = "{module}.server:main"

[tool.uv.sources]
mcp-platform = {{ git = "https://github.com/ump45nose/mcp-platform.git", tag = "v0.1.3" }}

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{module}"]
''')
    manifest = {
        "schema_version": 1, "id": name, "name": name, "command": [name + "-server"],
        "public_url": "https://" + name + ".example.com", "host_port": 18100,
        "volumes": [{"name": name + "-data", "mount": "/data"}],
        "environment": {"HOST": "0.0.0.0", "PORT": "8080", "MCP_DEVELOPMENT_NO_AUTH": "false",
                        "OAUTH_STORAGE_PATH": "/data/oauth"},
        "auth": {"client_id": name, "discovery_url": "https://auth.example.com/.well-known/openid-configuration"},
        "refresh_token_lifetime_days": 180,
        "required_env": ["OIDC_CLIENT_SECRET", "OAUTH_JWT_SIGNING_KEY", "OAUTH_STORAGE_ENCRYPTION_KEY", "OIDC_AUTHORIZED_USERNAMES"],
    }
    AppManifest.model_validate(manifest)
    (destination / "mcp.app.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (destination / ".env.example").write_text("MCP_DEVELOPMENT_NO_AUTH=true\nHOST=127.0.0.1\nPORT=8080\n")
    (destination / ".gitignore").write_text(".env\n.venv/\n__pycache__/\ndist/\n*.egg-info/\n")
    (destination / "README.md").write_text(f"# {name}\n\n引用 mcp-platform v0.1.3 的最小 MCP。\n\n"
        f"本地开发：`cp .env.example .env`，`uv sync --python 3.12`，`uv run {name}-server`。\n\n"
        "部署前修改 mcp.app.yaml 的域名、端口和认证配置，提交 uv.lock。"
        "在 NAS 目标配置登记 source_roots，运行 mcpctl plan 和 mcpctl deploy。\n")
    print(f"项目已创建: {destination}")


def package_app(app, source, output):
    """从清单生成元数据，保留原插件扩展；只打包明确的展示文件。"""
    if not app.plugin:
        raise ValueError("清单未配置 plugin")
    spec = app.plugin
    plugin = json.loads((source / "plugin.json").read_text()) if (source / "plugin.json").exists() else {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "author": {"name": "yuwk"}, "extensions": {"com.openai": {}},
    }
    if plugin.get("name", spec.name) != spec.name:
        raise ValueError("插件身份与清单不一致")
    plugin.update(name=spec.name, version=spec.version, description=spec.description, keywords=spec.keywords)
    extension = plugin.setdefault("extensions", {}).setdefault("com.openai", {})
    interface = extension.setdefault("interface", {})
    interface.update(displayName=spec.display_name, longDescription=spec.description)
    if spec.short_description is not None:
        interface["shortDescription"] = spec.short_description
    if spec.brand_color is not None:
        interface["brandColor"] = spec.brand_color
    if spec.logo:
        interface.update(logo="./" + spec.logo, composerIcon="./" + spec.logo)
    if bool(spec.app_id) != bool(spec.app_binding):
        raise ValueError("App ID 和绑定必须同时提供")
    binding = {"apps": {spec.app_binding: {"id": spec.app_id}}} if spec.app_id else {"apps": {}}
    if (source / ".app.json").exists():
        original_binding = json.loads((source / ".app.json").read_text())
        if original_binding != binding:
            raise ValueError("清单 App ID 与已有绑定不一致，拒绝替换身份")
    if spec.app_id:
        extension["apps"] = "./.app.json"
    elif extension.get("apps"):
        raise ValueError("已有 App 声明缺少清单中的真实绑定，拒绝丢弃身份")
    codex_plugin = {k: v for k, v in plugin.items() if k not in {"$schema", "extensions"}}
    codex_plugin.update(extension)
    files = {
        "plugin.json": json.dumps(plugin, ensure_ascii=False, indent=2).encode(),
        ".codex-plugin/plugin.json": json.dumps(codex_plugin, ensure_ascii=False, indent=2).encode(),
        "mcp-connection.json": json.dumps({"url": app.public_url + app.mcp_path, "transport": "streamable-http"}, indent=2).encode(),
        "接入说明.md": (
            f"# {app.name}\n\nMCP 地址：{app.public_url}{app.mcp_path}\n\n"
            "更新同一服务时沿用原 App 和插件身份。首次连接需登录 Authelia 并同意授权。\n"
            "现有 GPT/dots 连接应直接重试只读工具；不要重新创建 App。\n"
        ).encode(),
    }
    if spec.app_id:
        files[".app.json"] = json.dumps(binding, ensure_ascii=False, indent=2).encode()
    else:
        if app.authentication != "oauth":
            raise ValueError("新 GPT Web 插件的远程 MCP 入口需要先提供 OAuth")
        servers = {app.id: {"type": "streamable-http", "url": app.public_url + app.mcp_path}}
        files["mcp.json"] = json.dumps({
            "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
            "mcpServers": servers,
        }, indent=2).encode()
        files[".mcp.json"] = json.dumps({"mcpServers": servers}, indent=2).encode()
        codex_plugin["mcpServers"] = "./.mcp.json"
        files[".codex-plugin/plugin.json"] = json.dumps(codex_plugin, ensure_ascii=False, indent=2).encode()
    if spec.logo:
        logo = (source / spec.logo).resolve()
        if not logo.is_relative_to(source.resolve()) or not logo.is_file():
            raise ValueError("插件图标必须是业务仓库内的文件")
        files[spec.logo] = logo.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(spec.name + "/" + name, content)
    print(f"插件包已生成: {output}；沿用已核实的 App 绑定或远程 MCP 入口")


def doctor(target):
    report = {"docker": run(["docker", "version", "--format", "{{.Server.Version}}"] ).strip(),
              "compose": run(["docker", "compose", "version", "--short"]).strip()}
    for file in (target.tunnel_config, target.tunnel_compose, target.authelia_config, target.cloudflare_env):
        if not Path(file).is_file():
            raise ValueError(f"目标配置文件不存在: {file}")
    report["tunnel"] = run(["docker", "inspect", target.tunnel_container,
                           "--format", "{{.State.Running}}"] ).strip()
    report["authelia"] = run(["docker", "inspect", target.authelia_container,
                            "--format", "{{.State.Running}}"] ).strip()
    cf = Cloudflare(target)
    try:
        if target.cloudflare_zone_id:
            cf.request("GET", f"zones/{target.cloudflare_zone_id}/dns_records", params={"per_page": 1})
        else:
            cf.request("GET", "zones", params={"per_page": 1})
        report["cloudflare"] = "credentials_valid"
    finally:
        cf.client.close()
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="MCP 公共基座部署工具")
    parser.add_argument("--version", action="version", version="mcp-platform " + version("mcp-platform"))
    parser.add_argument("--targets", type=Path, default=default_targets())
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="创建业务项目")
    init.add_argument("name")
    init.add_argument("--directory", type=Path)
    doctor_parser = sub.add_parser("doctor", help="检查已有 NAS 设施和凭据")
    doctor_parser.add_argument("--target", default="nas")
    for name in ("plan", "deploy", "rollback", "package"):
        command = sub.add_parser(name)
        command.add_argument("app")
        command.add_argument("--source", type=Path)
        command.add_argument("--target", default="nas")
        if name in ("deploy", "rollback"):
            command.add_argument("--auth-only", action="store_true", help="仅协调认证配置，保留业务镜像及入口")
        if name == "package":
            command.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            init_project(args.name, (args.directory or Path.cwd() / args.name).resolve())
            return
        target = load_target(args.targets, args.target)
        if args.command == "doctor":
            doctor(target)
            return
        source = resolve_source(args.app, target, args.source)
        app = load_app(source)
        if app.id != args.app:
            raise ValueError("清单 ID 与部署应用不一致")
        if args.command == "package":
            package_app(app, source, args.output or source / "dist" / (app.id + "-plugin.zip"))
        elif args.command == "plan":
            from dotenv import dotenv_values
            env_path = Path(target.env_files.get(app.id, ""))
            env = {**dict(dotenv_values(env_path)), **app.runtime_environment} if env_path.is_file() else {}
            try:
                auth_change = prepare_auth_change(app, target, env)
                changed_auth = auth_change.changed if auth_change else False
            except KeyError as error:
                if app.auth is None or error.args != (app.auth.secret_env,):
                    raise
                auth_change, changed_auth = None, None  # 首次凭据由 deploy 初始化。
            cf = Cloudflare(target)
            try:
                cf.find_zone(app.hostname)
                records = cf.records(app.hostname)
                print(json.dumps({"app": app.id, "source": str(source), "endpoint": app.public_url + app.mcp_path,
                    "deployment_mode": app.deployment_mode, "authentication": app.authentication,
                    "auth_change": changed_auth,
                    "authelia_change": changed_auth if app.oauth_provider == "authelia" else False,
                    "mcphub_change": changed_auth if app.oauth_provider == "mcphub" else False,
                    "oauth_provider": app.oauth_provider,
                    "refresh_token_lifetime_days": app.refresh_token_lifetime_days,
                    "tunnel_change": tunnel_text(Path(target.tunnel_config).read_text(), app) != Path(target.tunnel_config).read_text(),
                    "dns_types": [r["type"] for r in records], "existing_env": env_path.is_file(),
                    "volumes": [v.name for v in app.volumes]}, ensure_ascii=False, indent=2))
            finally:
                cf.client.close()
        elif args.command == "deploy":
            if args.auth_only:
                deploy_auth_only(app, source, target)
            elif app.deployment_mode == "existing":
                deploy_existing(app, source, target)
            else:
                deploy(app, source, target)
        else:
            if os.geteuid() != 0:
                raise PermissionError("回滚需要 sudo -n 权限")
            with deployment_lock(target):
                current_path = Path(target.runtime_root) / app.id / ("auth-current.json" if args.auth_only else "current.json")
                current = json.loads(current_path.read_text())
                journal = Journal(Path(current["journal"]))
                rollback_journal(app, target, journal)
                old = journal.data.get("previous", {}).get("state")
                if old:
                    private_write(current_path, json.dumps(old, indent=2))
                else:
                    current_path.unlink(missing_ok=True)
                print("本次代码和配置已回滚；业务数据与 OAuth 状态未恢复旧快照")
    except Exception as error:
        # pydantic 和第三方错误可能包含输入；完整诊断只写入私有文件。
        diagnostic = Path(default_targets()).parent / "last-error.log"
        private_write(diagnostic, str(error))
        if isinstance(error, (ValueError, KeyError)):
            print(f"配置或输入校验失败；私有诊断: {diagnostic}", file=sys.stderr)
        elif isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print(f"{type(error).__name__}；私有诊断: {diagnostic}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
