# Steam NAS 部署与验收准备 — 2026-10-07

Steam 业务分支 `steam-asf-adapter`（`a3b50bc`）已 fast-forward 合入并推送
`benefits-automation/main`。业务入口直接使用 NAS 上的本仓库，不增加业务源码副本。
部署、登录辅助入口、Hermes 封装和通知实现维护在 `nas-cron-jobs`。

## 已完成

- 按用户要求先提交现存 `nas-cron-jobs` 改动：`8b8a5b0`。
  此检查点保存原有 Personal Data Hub 源码链接，未混入 Steam 部署改动。
- 审阅 Steam 配置、IPC、发现、证据门槛、journal 和执行流程。
  默认 `--execute` 只读；部署参数不含 `--claim`。
- 在独立临时源码目录运行已有 Steam 测试，43 项全部通过。
  这些是模拟接口测试；没有把它们当成真实账号入库证明。
- ASF 6.3.10.3 容器健康，加载 FreePackages 1.7.1.1。
  固定镜像摘要为
  `sha256:446ef7f44cb7eba3aaa8b954fc62791f3bdd1a79c441d4cb39f59cac8a6986b9`。
  插件下载与 GitHub 发布摘要一致：
  `sha256:949a7be69d8c03bb85f1c8e8d169eea37c1c363166227237110e62e9c66e1961`。
- 全局和插件更新、Watchtower 更新均关闭。初始 bot 禁用、挂卡暂停、
  `EnableFreePackages=false`。没有启动 Steam 登录，没有发送领取请求。
- 持久目录位于源码外，由 Hermes runtime UID 988/GID 984 持有；
  私有目录 0700，配置 0600。IPC 密钥未出现在配置之外的日志中。
- 无认证 `/Api/ASF` 返回 401；正确认证返回 200、版本匹配。
  真实 `/Api/Bot/Main` 返回 200 且未登录。
  正在运行的 Swagger 中存在 GetChangesSince、GetProductInfo、
  GetOwnedPackages 和 RequestFreeSubLicense 的预期路由。
- 未登录时上述三个 FreePackages 只读路由均返回 400，符合需要会话的限制；
  不代表 PICS/owned 的实际响应内容已验收。
- 宿主身份无代理、无 Cookie 访问 Steam 官方公开 app 页面返回 200，解析出
  3 个购买块。未指定账号国家，因此这只证明公开商店传输和解析可用，
  不证明某个账号地区的实际永久限免证据。
- 安装并执行真实 Hermes 薄入口。结果原子保存为
  `private_file_unreadable`，正确反映首次登录尚未生成私有账号配置；
  未掩盖为 no-candidate 或业务成功。
- Hermes `benefits-steam-readonly` 已登记，每小时第 7、37 分，Asia/Taipei，
  no-agent、local delivery；目前暂停。现有中午福利告警读取 Steam 结果，
  区分发现覆盖不足、登录问题和只读合格但未领取的候选。
- 一条 Steam 部署测试通知通过现有专用 notice bot，返回信息确认送达原福利话题。
  独立通知探针补上现有 Hermes HTTP 代理后通过；定时通知的原有网络配置未改。
- NAS 开机清单已包含 ASF；只读清单检查未发现缺失或已停用的计划容器。
  只安装本次 Steam 相关文件，未执行全量 cron 部署或其他平台业务。

## 必须由用户完成的下一步

在用户自己的 NAS SSH 交互终端运行：

```sh
sudo -u hermes env -i PATH=/usr/bin:/bin python3 /home/yuwk/cron/scripts/steam-asf/login.py
```

提供精确 SteamID64 和 Steam 商店实际国家；账号名、密码及 Steam Guard 在终端
隐藏输入，IPC 只临时传入密码和验证码，不写入源码、配置或日志。
成功后仅在私有配置中保存登录名和 ASF 会话，用于重启恢复。
账号地区依赖用户确认，ASF bot 元数据不能证明该地区。

登录后再执行真实只读入口，核对 SteamID、PICS wire schema、自动发现、
真实地区官方永久赠送购买块与已有 package 查询。缺少当前合格活动时必须明确
记录未覆盖的正向证据分支。完成这一步后再启用只读 cron。
真实领取仍需额外明确授权；没有通过部署参数开放领取。

## 环境事实登记

已通过 `shared-state` MCP 的 `codex` 读取身份检查 host/container 基线，
没有修改采集器维护的键。按 `/home/hermes/AGENTS.md` 的 Codex 只读约束，
本次非采集器部署事实留待可写运维路径登记，不声称已写入 shared-state。
完整 `domain/id/value` 在 NAS 的
`/home/yuwk/cron/steam-asf/shared-state.pending.json`；目标是
`infra/benefits_steam_deployment`，登记后需同键复读。

## 版本来源与部署说明

- [ASF 6.3.10.3](https://github.com/JustArchiNET/ArchiSteamFarm/releases/tag/6.3.10.3)
- [FreePackages 1.7.1.1](https://github.com/Citrinate/FreePackages/releases/tag/1.7.1.1)，要求 ASF 6.3.3.3 或更新。
- [ASF Docker](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/Docker)
- NAS 部署与恢复说明：`nas-cron-jobs/steam-asf/README.md`。

版本来源用 `smart-search fetch` 及 GitHub release API 核对；IPC wiki 页面抓取
失败，接口以固定发布源码和正在运行的 Swagger 核对，没有据抓取失败推断协议。
