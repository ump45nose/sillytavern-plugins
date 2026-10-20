# benefits-automation

各平台的 Linux 一次性脚本集合。每个平台有独立入口和业务模块，按需使用 `common/` 的运行、锁、结果和凭据能力。HTTP 签到不加载浏览器库；浏览器任务串行，用完即关闭。

**Hermes 负责调度、日报汇总和通知。** 本仓库的边界是执行平台操作、输出 JSON 并保存执行结果，不包含 Hermes cron、Telegram 推送、消息队列、浏览器池或容器部署要求。

## 平台与当前验收

| 平台 | 独立入口 / 说明 | NAS 实测记录 |
|---|---|---|
| 什么值得买 | [SMZDM](platforms/smzdm/README.md) | 签到确认；奖励查询未确认 |
| V2EX | [V2EX](platforms/v2ex/README.md) | 今日奖励确认 |
| 阿里云开发者社区 | [Aliyun](platforms/aliyun/README.md) | CookieCloud 最新 Cookie，签到与待收积分确认 |
| Laowang | [Laowang](platforms/laowang/README.md) | 自动验证码、提交和签到读回通过 |
| Microsoft Rewards | [Rewards](platforms/rewards/README.md) | 2026-10-20：搜索、APP 等已确认；每日投票及探索 0/40 未完成 |
| Epic 免费游戏 | [Epic](platforms/epic/README.md) | 2026-10-20：核验 Bad Cheese 手动入库；自动领取仍被验证码/支付流程阻塞 |

[Steam ASF / FreePackages](platforms/steam/README.md) 已合入 main 并部署到 NAS：登录、持久恢复、真实接口、定时和通知已核验。用户已授权免费领取，Arena of Trophies 实际取得免费许可，owned 回查与防重复检查通过；公开商店超时的代理路由已修复，Hermes 已启用经核实的限免领取。缺少访问 token 的包继续待核查，合格普通游戏的限时赠送正向样本仍待实际活动覆盖。见 [2026-10-07 部署与验收记录](docs/STEAM_DEPLOYMENT_2026-10-07.md)。这次 Steam 部署独立于下述六平台生产迁移。

Epic 当前阻塞及回归清理见 [2026-10-20 记录](docs/plans/2026-10-20-benefits-regression-cleanup.md)，Rewards 实际进度见 [能力与现场验收](docs/REWARDS_PARITY.md)。原六平台迁移历史见 [实现验收记录](docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md) 和 [生产迁移记录](docs/MIGRATION_2026-10-03.md)。生产启动已迁至 Hermes no-agent cron，六条旧青龙任务已停用。京东和中国移动不在当前六个平台中。

## 结构

2026-10-19 新增 [GLaDOS](platforms/glados/README.md)、[影视飓风](platforms/yingshijufeng/README.md)、[Olé](platforms/ole/README.md)、[雨云](platforms/rainyun/README.md)、[WorkBuddy 双版](platforms/workbuddy/README.md)、[WeTalk](platforms/wetalk/README.md) 的独立执行器。[Telegram 机器人签到](platforms/telegram/README.md) 通过账号自己的 Telegram Web 会话按 `--account` 给配置的机器人发送签到命令，支持多账号，尚待用户扫码登录后真实验收。[网易严选](platforms/yanxuan/README.md) 目前只有积分只读查询，尚未实现当前活动签到，不能为它注册签到任务。微信两平台共用 [YYB 取码服务](docs/YYB_LOGIN.md)。配置、真实账号验收和仍需处理的事项见 [新增平台验收记录](docs/NEW_PLATFORM_ACCEPTANCE_2026-10-19.md)；代码或离线测试通过不代表已经签到。

```text
common/                小型公共库；没有平台名分支或常驻进程
platforms/<platform>/  run.py、业务模块、平台 README、各自依赖
locks/                 Python 依赖锁，含传递依赖与 hash
upstream/              来源与行为对照；不作为运行入口
source-lock.json        原始来源的固定提交
```

每个平台入口声明自己的参数、环境变量、超时和是否使用浏览器。Node 浏览器平台用 `common/persistent_browser.cjs` 校验固定版本依赖、打开并关闭 `state/<platform>/<account>/browser/` 持久 profile，以及在终端完成交互登录；浏览器库由平台目录自己的 `node_modules` 传入，公共库不安装或加载浏览器。可单独调用；抽离发布时携带该平台所需公共库和许可证即可，不必安装其他平台依赖。运行数据必须放源码仓库外；账号使用代号，不用邮箱。

## 运行

已验证 NAS：Linux x86_64，CPython 3.12.13，Node 24.21.0。Python 启动器只依赖标准库。各平台依赖安装见对应 README。

```sh
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data --account account1 --execute
```

不加 `--execute` 不访问平台，只验证入口/目录/锁并报告 `execution_not_requested`。凭据通过平台环境变量或仓库外私有配置提供，禁止放命令行、源码或 Git。可选 `COOKIECLOUD_CONFIG` 是一次性读取已有 CookieCloud 的配置文件路径，已接入 Aliyun、Laowang、GLaDOS；不增加同步服务。

所有入口在同一主机使用同一个绝对 `--runtime-root`，共享浏览器互斥锁。默认业务日期时区为 Asia/Shanghai，可用 `--timezone` 修改；平台任务资格和积分按其当前返回值判断，不强行执行其他地区下一天的活动。

## 结果契约

标准输出是一条 JSON，同时原子保存 `runs/<run-id>/result.json` 和 `results/<platform>/<account>/latest.json`。Rewards 按模式分别保存 latest。包含 run ID、平台、账号代号、业务日期、起止时间、耗时、执行状态、原因和业务状态；`details.metrics` 交付进度/余额变化/奖励/数量，`details.items` 交付任务与游戏明细。未核实数值为 null，不能按 0 处理。Hermes 可直接读取，不需要通知 SDK。完整字段见 [结果契约](docs/RESULTS.md)。

| 退出码 | 含义 |
|---|---|
| 0 | 执行正常，业务均完成或不适用 |
| 1 | 执行失败或未请求执行 |
| 3 | 执行正常，仍有未知、未完成或受限项 |
| 75 | 锁忙，没有执行平台动作 |
| 124 | 总时限耗尽；可能保留部分已确认结果 |

未知结果不算成功。动作发送前记下 intent；不明确的提交以只读查询恢复，不盲目重复。成功签到不会因其他奖励未知而重做。跨次执行只保留可核实事实，不用旧汇总结果跳过整个平台。

## 资源与生命周期

没有后台进程；空闲时脚本本身不占用常驻内存。每次持有账号锁，浏览器任务再持有全局锁，整个调用受超时监督。阶段顺序执行，不保留浏览器池。原生 Chromium 保留 sandbox；不关闭 TLS 验证。

Linux subreaper/pidfd 负责一次性启动器的后代回收；回收无法确认时阻止下一次浏览器重叠运行。只读检查及恢复说明见 [RUNTIME_RECOVERY](docs/RUNTIME_RECOVERY.md)。日志每次最多 1 MiB，结果最多 64 KiB，新文件默认 0600、目录 0700。日志脱敏不能替代对未知凭据格式的检查；通用运行历史没有自动删除策略。

这里只记录平台结果。Hermes 的实际 cron、私有凭据配置和日报读取器维护在仓库外，切换按平台停旧任务再启新入口，避免双跑。依赖边界和许可证见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
