# Steam NAS 部署与只读验收 — 2026-10-07

Steam 业务分支 `steam-asf-adapter`（`a3b50bc`）已 fast-forward 合入并推送
`benefits-automation/main`。业务入口直接使用 NAS 上的本仓库；部署、登录辅助入口、
Hermes 封装与通知维护在 `nas-cron-jobs`。账号首次登录和持久重启恢复已完成，
只读定时任务已启用。尚未发送任何领取请求，也未完成合格普通游戏的领取验收。

## 部署与账号

- 按用户要求先提交原有 `nas-cron-jobs` 改动：`8b8a5b0`，保留既有
  Personal Data Hub 源码链接。Steam 模拟接口测试在隔离源码目录运行，43 项通过。
- ASF 6.3.10.3 与 FreePackages 1.7.1.1 已部署；固定镜像摘要为
  `sha256:446ef7f44cb7eba3aaa8b954fc62791f3bdd1a79c441d4cb39f59cac8a6986b9`，
  插件下载与发布摘要一致：
  `sha256:949a7be69d8c03bb85f1c8e8d169eea37c1c363166227237110e62e9c66e1961`。
- ASF、插件及 Watchtower 自动更新关闭，挂卡暂停，远程通信关闭，
  `EnableFreePackages=false`。部署参数不含 `--claim`。
- 持久数据位于源码外的 `/vol2/1000/Docker/benefits-automation/steam-asf`，
  runtime UID 988/GID 984 持有；私有目录 0700、账号配置和会话数据库 0600。
  该目录不受 `/home/hermes` ACL 扩权任务影响。配置中没有密码或 Guard 码。
- 用户在 NAS 隐藏输入终端完成授权，实际 SteamID 与预期值一致。
  账号登录名和刷新会话只保存在私有数据中。CN 地区由用户确认；不根据 ASF
  网络出口国家推断账号实际商店地区。
- 使用正常 Compose 配置实际重启 ASF，自动恢复同一个 SteamID 的已登录会话。
  服务为 headless、Debug=false；IPC 只发布到 `127.0.0.1:1242`。
  无认证请求返回 401，正确认证返回 200。IPC 密钥未出现在 Docker 日志中。
- 扫码入口曾遇到 SteamKit2 超时。辅助程序已限制重试、停止容器后才改配置、
  清理临时 QR 文件并恢复正常部署。扫码阶段仅记录时间、级别、方法和异常类型，
  不记录原始消息、授权链接或异常正文。此次成功登录使用隐藏终端输入入口。

## 真实只读证据

- 真实 `/Api/Bot/Main` 身份验证通过。`GetOwnedPackages` 返回 276 个 uint 条目，
  包括零号基础条目；修复客户端错误地拒绝整个响应的问题后，得到 275 个有效
  正数 package。零号条目不参与候选。相关 IPC 回归检查 6 项通过，修复提交
  `4426682` 已推送。
- 已拥有 package 与公开 app 的真实 `GetProductInfo` KeyValues 树通过严格解析；
  `GetChangesSince` 实际响应和后续增量变化可读取。
- 无代理、无 Cookie 访问真实 CN 官方商店 app 10 页面，解析出 3 个购买块，
  不把普通购买页面识别成永久赠送。
- 两个真实 CN 官方促销样本的永久赠送说明和同一购买块里的免费 license package
  对应关系均通过 `official_offer`：

| 官方样本 | package | 真实 PICS | 业务结果 |
|---|---:|---|---|
| [Rotwood: Drakin Armoury Pack](https://store.steampowered.com/app/5067220/?cc=CN&l=english) | 1835073 | NoCost、SinglePurchase、Available，expiry=1792083600 | app 类型为 DLC，拒绝 |
| [MXGP 26 - Scrubdesignz Liveries](https://store.steampowered.com/app/4847440/?cc=CN&l=english) | 1782945 | 同上 | app 类型为 DLC，拒绝 |

这证明当前官方证据解析的正向路径与 DLC 排除规则；两个样本都不属于业务接受的
普通游戏。未把它们当成合格候选，也没有尝试领取。当前样本未覆盖“合格普通游戏
自动发现到 dry_run_eligible”的完整正向分支，需要实际活动出现后继续核验。

## 发现窗口与尚未核验项

首次 `GetChangesSince/0` 返回 `RequiresFullUpdate=true`；这不能证明启动前的
活动已扫描。首次只读 run `f25b175c-a70d-48ad-b032-9b6d54eb0fbb` 正确记录为
`discovery_coverage_incomplete`。旧结果和历史缺口没有改写为成功。

已在 SteamID 锁内备份账号配置和发现状态，然后把增量基线明确设为首次核对的
变更号 `39563190`，保留当前游标与全部待核查队列。私有
`discovery-window.json` 标明该基线之前的历史未核验；配置与发现状态需成对恢复。
后续仅声称监控这个窗口的变化，不能宣称全站无活动。

Hermes 实际调度 run `24c2d66a-0804-4606-b11e-99167fd3d337` 在
2026-10-07 13:44（Asia/Taipei）保存为 execution=ok，扫描 15 个变化包，
候选 0、领取 0；business.discovery=unknown，原因是
`discovery_candidates_require_review`。抽查未核验包的真实 PICS 响应为
`MissingToken=true`、空 metadata，而两个公开促销包不需要该 token。
这是上游访问数据缺失，保留为 blocked 并轮转复查，不当作无活动或可领取。

## 调度、通知与恢复

- Hermes `benefits-steam-readonly` 已启用，`7,37 * * * *`、Asia/Taipei，
  no-agent、local delivery。通过 Hermes API 排入一次立即运行，由真实调度器
  执行并读回 last_status=ok；常规下一次执行为 14:07。
- 实际调度、结果保存和未核验业务状态分别验证；没有把进程成功当成领取成功。
- 原中午福利告警读取 Steam 和既有六个平台，仅报告异常或待授权项。当前真实
  Steam 结果的告警渲染已验证，并经现有专用 notice bot 确认送达原福利话题。
  Telegram 使用既有通知代理；Steam IPC 和商店请求仍无代理，未更改账号地区。
- NAS 开机清单包含 ASF；此前清单检查无缺失或计划容器停用。只部署 Steam
  相关文件，未执行全量 cron 部署或其他平台业务。
- 回退时通过 Hermes API 暂停 Steam 任务，再停止该 ASF 服务；保留账号会话、
  discovery 队列和 journal。不能删除 intent 来重新提交。真实领取需另行明确授权。

## 环境事实登记

通过 `shared-state` MCP 的 `codex` 读取身份核对 host/container 基线。
按 `/home/hermes/AGENTS.md` 的 Codex 只读约束，没有修改采集器键或声称写入成功。
非采集器部署事实的完整 `domain/id/value` 保存在
`/home/yuwk/cron/steam-asf/shared-state.pending.json`，目标为
`infra/benefits_steam_deployment`；可写运维路径登记后需同键复读。

## 版本来源

- [ASF 6.3.10.3](https://github.com/JustArchiNET/ArchiSteamFarm/releases/tag/6.3.10.3)
- [FreePackages 1.7.1.1](https://github.com/Citrinate/FreePackages/releases/tag/1.7.1.1)，要求 ASF 6.3.3.3 或更新。
- [ASF Docker](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/Docker)
- 部署与恢复说明：`nas-cron-jobs/steam-asf/README.md`。

版本使用 smart-search 和 GitHub release API 核对。IPC wiki 抓取失败，协议核验
依据固定发布源码、运行中的 Swagger 和以上真实响应。促销搜索仅用来找到样本，
最终判断来自官方 CN 商店与真实 PICS，不采纳搜索摘要作为活动或地区证明。
