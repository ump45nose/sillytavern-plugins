# benefits-automation

六个平台的 Linux 一次性脚本集合。每个平台有独立入口和业务模块，按需使用 `common/` 的运行、锁、结果和凭据能力。HTTP 签到不加载浏览器库；浏览器任务串行，用完即关闭。

**Hermes 负责调度、日报汇总和通知。** 本仓库的边界是执行平台操作、输出 JSON 并保存执行结果，不包含 Hermes cron、Telegram 推送、消息队列、浏览器池或容器部署要求。

## 平台与当前验收

| 平台 | 独立入口 / 说明 | 2026-10-03 NAS 实测 |
|---|---|---|
| 什么值得买 | [SMZDM](platforms/smzdm/README.md) | 签到确认；奖励查询未确认 |
| V2EX | [V2EX](platforms/v2ex/README.md) | 今日奖励确认 |
| 阿里云开发者社区 | [Aliyun](platforms/aliyun/README.md) | CookieCloud 最新 Cookie，签到与待收积分确认 |
| Laowang | [Laowang](platforms/laowang/README.md) | 自动验证码、提交和签到读回通过 |
| Microsoft Rewards | [Rewards](platforms/rewards/README.md) | 每日活动、桌面搜索、APP 签到/活动确认；探索必应仍在验收 |
| Epic 免费游戏 | [Epic](platforms/epic/README.md) | 当前免费游戏已在库，原生轮询确认；新订单待验证 |

最新证据见 [实现验收记录](docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md) 和 [生产迁移记录](docs/MIGRATION_2026-10-03.md)。生产启动已迁至 Hermes no-agent cron，六条旧青龙任务已停用。Epic 新订单与 Rewards 未确认项保留为使用中的待完善能力。京东和中国移动不在当前六个平台中。

## 结构

```text
common/                小型公共库；没有平台名分支或常驻进程
platforms/<platform>/  run.py、业务模块、平台 README、各自依赖
locks/                 Python 依赖锁，含传递依赖与 hash
upstream/              来源与行为对照；不作为运行入口
source-lock.json        原始来源的固定提交
```

每个平台入口声明自己的参数、环境变量、超时和是否使用浏览器。可单独调用；抽离发布时携带该平台所需公共库和许可证即可，不必安装其他平台依赖。运行数据必须放源码仓库外；账号使用代号，不用邮箱。

## 运行

已验证 NAS：Linux x86_64，CPython 3.12.13，Node 24.21.0。Python 启动器只依赖标准库。各平台依赖安装见对应 README。

```sh
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data --account account1 --execute
```

不加 `--execute` 不访问平台，只验证入口/目录/锁并报告 `execution_not_requested`。凭据通过平台环境变量或仓库外私有配置提供，禁止放命令行、源码或 Git。可选 `COOKIECLOUD_CONFIG` 是一次性读取已有 CookieCloud 的配置文件路径，目前接入 Aliyun、Laowang；不增加同步服务。

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
