# fn 部署验收：2026-10-10

- 正式服务：`infra/app`，容器 `subboost-app-1`；入口仍为 `http://192.168.31.201:13000`。
- 镜像：`local/subboost:2.8.1-android-tailscale-v1`，镜像 ID `sha256:fbd265cbf5f3b5439d81ca567cdd04c6cc337444b17d7d6a00c59ab997e7e2ab`。
- 订阅采用附加输出：原链接后加 `?profile=android-tailscale`。数据库仍只有一条订阅，原节点、来源、配置、token 与 owner 保持；没有复制订阅记录。
- 手机输出在现有 92 个代理节点、201 条原规则之外追加一个 `TAILNET` 节点、4 条前置规则与 Tailnet DNS。普通订阅与变更前逐字一致。
- CMFA 2.11.32 固定内核源码包含 Tailscale 出站、`ts://` DNS 和 Android socket protect。独立 Linux Mihomo 1.19.26 `with_gvisor` 已通过新增配置的 `-t` 检查，该检查没有注册 Tailscale 身份。
- 11 项相关测试、完整 Next 生产构建与 TypeScript 检查通过。临时容器和正式服务均通过真实订阅验证；鉴权、订阅更新周期、现有分组与公网 DNS 保持。
- 正式 Compose 在宿主与 Dockge 内验证通过，只改变 `app.image` 与 Watchtower 排除标签。原生 `node` 用户、入口命令、环境、认证、数据库、端口、网络及无挂载状态保持。其余 9 个 infra 容器 ID 未变。
- 临时测试容器已移除，常驻容器和启动计划未新增。启动检查通过：47 个常驻容器，`missing=[]`、`active_unplanned=[]`、`stopped_planned=[]`。

私有回退与手机导入文件在 `/vol2/1000/Docker/subboost/backups/android-tailscale-20261010-161806/`。`mobile-subscription.private.txt` 是可在手机导入的 URL，`mobile-config.private.yaml` 是对应配置快照；均含凭据，不进入 Git。

手机侧仍需首次登录新 Tailscale 身份、关闭 CMFA 绕过私有网络，并在移动数据下验证家庭 IP、完整 MagicDNS 名、国内直连与国外代理。后台保活和 Android 实际 VPN 行为尚未实机验收，按 [README](README.md) 操作。
