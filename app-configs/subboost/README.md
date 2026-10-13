# Android 上的代理与 Tailscale

手机只开启 Clash Meta for Android（CMFA）的 VPN，由内置 Mihomo 同时处理代理和 Tailscale 出站。无需 root，也无需 NAS 承担互联网出口。

本次部署与已验证范围见 [2026-10-10 验收记录](DEPLOYMENT.md)。

## 手机接入

1. 在家里 Wi-Fi 打开 [SubBoost](http://192.168.31.201:13000)，复制现有订阅的 YAML 链接，在末尾追加 `?profile=android-tailscale`，在 CMFA 中新建 URL 配置。以后手机更新这个链接即可，PC 继续使用原链接。
2. CMFA 2.11.32 使用 **规则模式**，关闭设置里的 **绕过私有网络**。如果开了全局覆写，不要覆写本配置的 `nameserver-policy`、fake-IP 过滤或模式。系统私人 DNS 先设为自动/关闭进行首轮验证。
3. 启动 CMFA，访问 `http://192.168.31.201:13000` 或 NAS 的 Tailscale IP，触发 `TAILNET` 节点。在客户端日志里打开 Tailscale 登录链接并授权。控制台会出现独立的 `xiaomi-14-pro-mihomo` 设备；它与官方 Tailscale App 的旧身份不同。
4. 关闭官方 Tailscale App 的 VPN，只保持 CMFA；给 CMFA 开启后台运行、自启动和系统始终开启 VPN。MIUI/HyperOS 的电池限制需要在手机侧设置。
5. 关闭 Wi-Fi、改用移动数据验证家庭 IP、MagicDNS 完整域名、国内直连和国外代理。确认后将这份配置设为日常默认。

首次 Tailscale 请求可能超时，完成登录后重试。后续配置刷新仍使用应用私有目录下的 `clash/tailscale/android-mihomo` 状态；不要清除 CMFA 应用数据。需要长期无人值守时，在 Tailscale 控制台按自己的策略管理这个新设备的密钥到期。

同一模板可导入另一台手机，但每台手机会独立注册身份。需要不同名称时修改 `android-tailscale.json` 的 hostname 并提供另一份 profile。

## 分流与边界

| 目标 | 手机出站 |
| --- | --- |
| `192.168.31.0/24` | Tailscale → 已批准的家庭子网路由 |
| `100.64.0.0/10`、`fd7a:115c:a1e0::/48` | Tailscale → 对应 Tailnet 设备 |
| `*.tail0292a9.ts.net` 及根域 | Tailscale；DNS 使用 `ts://TAILNET` |
| 国内与国外互联网 | 保留现有 SubBoost 分流、直连和代理节点 |
| 其他私有网段 | 保留原规则 |

配置没有 `exit-node`、`auth-key`。外网流量不会经 NAS；访问没有 Tailscale 的家庭设备时，NAS 作为子网路由器转发是必需的。Tailnet 设备之间由 Tailscale 尝试直连，必要时可能走 DERP。

新家庭设备落在上述 `/24` 内便自动适用，新 Tailnet 设备使用其 IP 或完整 MagicDNS 名便自动适用。新增家庭网段时，需要发布/批准对应子网路由，再修改 `homeSubnets` 并重建镜像。短主机名、mDNS `.local` 和局域网广播发现不由这些规则自动提供。整个 CGNAT 地址段被用于 Tailnet；若某运营商本身提供同段内部服务，需要为该服务加例外。

订阅仍由现有数据库生成，手机与 PC 共用节点来源、配置和定时更新，不复制订阅记录。只是请求手机专用链接时，在生成完成后加入节点、前置规则和 DNS 策略。普通链接的 YAML 保持原样。`TAILNET` 不加入外网测速/选择组，未来的 `include-all` 组也有排除规则。手机订阅更新在已启动的核心中按现有分流访问；首次导入先用家庭 Wi-Fi，VPN 停止时在外面无法访问内网订阅。

## 构建与恢复

固定上游 SubBoost **2.8.1** / commit `4a69b494b46d095c965be58cf425fe35a2c1e524`，基于现有官方镜像 digest `sha256:01f7d8e02486bf536e4da0fee2ce1dd1003294460cfeeb2c64d4295c7d0f4def` 构建。没有数据库 schema 变更。

```bash
bash subboost/build.sh
```

脚本下载固定源码到临时目录，应用小范围的路由补丁，运行 11 项相关测试，再构建 Next standalone。补丁应用位置变化时构建直接失败，升级上游前应重新审核。构建限制一个 Next worker，以减少 NAS 内存占用。

将 [compose.fragment.yaml](compose.fragment.yaml) 的 `app.image` 和 Watchtower 排除标签合入现有 `/vol2/1000/Docker/stacks/infra/compose.yaml`，其余 env、端口、网络、数据库和身份全部沿用。先保存旧 Compose 和镜像信息，再验证完整定义，只更新 `app`：

```bash
docker compose -p infra -f /vol2/1000/Docker/stacks/infra/compose.yaml config --quiet
docker compose -p infra -f /vol2/1000/Docker/stacks/infra/compose.yaml up -d --no-deps app
python3 /home/yuwk/cron/scripts/container-boot.py --check
```

NAS 的私有回退记录放在 `/vol2/1000/Docker/subboost/backups/android-tailscale-<时间>/`，含旧 Compose、原镜像引用、加密订阅快照和用于比较的私有 YAML。目录 `0700`、文件 `0600`。**订阅 token、节点凭据、加密主密钥和应用登录信息不进入本仓库。**

有私有基线时可运行验证，输出只包含统计与结果：

```bash
python3 subboost/verify.py /vol2/1000/Docker/subboost/backups/android-tailscale-<时间>
```

回滚时仅恢复 `app.image` 到上述官方 digest，移除本次增加的 Watchtower 标签，再运行同一个单服务更新命令。保留最新数据库数据和所有既有身份。手机需要切回普通订阅或官方 Tailscale App 才能继续组网。

## 依据

- [Mihomo 官方 Tailscale 出站说明](https://wiki.metacubex.one/config/proxies/tailscale/)
- [CMFA 2.11.32 固定内核版本](https://github.com/MetaCubeX/ClashMetaForAndroid/tree/v2.11.32/core/src/foss/golang/clash) 及 [对应 Tailscale 实现](https://github.com/MetaCubeX/mihomo/blob/e26714a181ac0e2fa803453c0a8e9a9ce94e31cb/adapter/outbound/tailscale.go)
- [CMFA 内置 HTTP 获取订阅](https://github.com/MetaCubeX/ClashMetaForAndroid/blob/v2.11.32/core/src/main/golang/native/config/fetch.go) 及 [内核分流拨号实现](https://github.com/MetaCubeX/mihomo/blob/e26714a181ac0e2fa803453c0a8e9a9ce94e31cb/component/http/http.go)
- [固定版本的 SubBoost 订阅输出](https://github.com/SubBoost/subboost/blob/4a69b494b46d095c965be58cf425fe35a2c1e524/local/app/api/subscriptions/%5Bid%5D/config.yaml/route.ts)

本方案的服务端验证与手机端体验分开记录。服务端配置生成、真实订阅差异和核心解析可在 NAS 检查；Android VPN 路由、首次登录、后台保活和移动数据下的最终分流必须在手机上验证。
