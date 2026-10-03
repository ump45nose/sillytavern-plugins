# NAS 验收：2026-10-03

## 结论

已将主分支 `a56e598205a772136f133629fa0a37752027c070` 克隆到 NAS 的 `/home/yuwk/benefits-automation`，安装原生 HTTP 和 Node 依赖，并做有限现场检查。**整套迁移验收未通过，当前不能删除青龙，也不能删除仍被旧部署使用的仓库。**

本轮未安装新的定时任务、容器、数据库或常驻服务。原生产调度保持运行；新入口在单独的、仓库外的私有验收目录运行。只做启动器、两种浏览器的本地页面冒烟和选定真实入口检查，没有运行整个回归测试集。

## 环境与验证范围

- Linux x86_64；此次实际执行的 Python 3.12.13、Node 24.21.0。与云端记录的 3.12.14 / 24.19.0 不完全相同，本记录只描述本次 NAS 环境
- HTTP 依赖通过仓库的 `--require-hashes` 锁安装，`pip check` 通过
- Patchright 1.61.1、playwright-firefox 1.63.0 使用各自 npm lockfile，安装禁用 scripts
- 复用现有镜像内的 Firefox revision 1543 和 Chromium headless shell revision 1228 二进制供原生验证，没有重新增加浏览器容器
- Firefox 持久 profile / 本地 HTML 冒烟通过；Chromium 本地 DOM 冒烟通过，sandbox 保持开启
- 六个不带 `--execute` 的入口均正确返回 `execution_not_requested`；没有将这些预期退出 1 当作业务失败
- 所有账号会话、凭据、运行日志及结果均在仓库外；未提交账号、Cookie、原始网页或数据库
- 现场入口结束后，全局浏览器清理标记已解除；这不构成 launcher 被强杀等全部生命周期场景的验收

## 平台结果

| 平台 | 本轮检查 | 结果和边界 |
| --- | --- | --- |
| 什么值得买 | 原生公开入口；导入旧记录中独立确认的今日签到事实，再查询奖励 | `checkin=complete`、`extra_reward=not_applicable`，普通 `reward=unknown`，退出 3。没有重复签到；本次不能宣称通过了全新一天的首次签到及全部奖励确认 |
| V2EX | 原生公开入口及一次只读恢复 | 首次返回 `provider_error` 并留下 pending；独立只读余额检查确认今日奖励，随后公开入口只读恢复返回 `reward_confirmed`、退出 0。说明账号会话可用，不表示所有首次领取异常已通过真实网站测试 |
| 阿里云 | 精确 hash 验证后的外部 daily.py + 当前部署 Cookie | `authentication_invalid`、退出 1。外部依赖 hash 匹配；当前认证失败，不是文件版本缺失 |
| laowang | 复制既有持久 profile 到验收目录，`--execute --status` | 能启动 Firefox 并读取站点状态；`not_signed`、退出 3。没有在本轮进行签到或挑战处理，不能算已完成自动签到验收 |
| Rewards | 既有单账号 desktop state 的原生 snapshot | `snapshot_unavailable`、退出 1；后续诊断能打开 dashboard，但没有读到进度条，flyout 读取也失败。未取得完整业务快照，没有把浏览器冒烟当作积分任务完成 |
| Epic | 公开 `run.py --execute` | `native_browser_and_approval_bindings_pending`、退出 1。当前 adapter.py 直接输出这个闸门结果；没有领取或复跑旧领取器 |

## Rewards 实际能力差距

本次从旧部署的实际 config.json 读取开关，而不是沿用上游默认值。UI 每日活动、extra 和以下旧配置一起构成当前需要保留的范围：

| 需要保留的能力 | 新 CLI 的绑定 |
| --- | --- |
| daily、extra、punchcards、desktop_search | 有绑定，尚需真实完整流程验收 |
| more_promotions、claim | 当前没有绑定 |
| app_daily、app_promotions | 有组件和可信调用方接口，普通 CLI 没有 APP client 绑定 |

已在**私有验收目录**建立上述八项 capabilities 清单，并调用真实 `createBindings` 进行无浏览器动作的核对；得到四项 bound、四项 missingBindings。最初缺清单的 `capability_manifest_required` 是部署配置检查，**补配置不能解决这四项缺失绑定**。没有通过关闭旧有能力使 full 看起来成功，也没有执行尚未通过快照预检的完整任务。

旧配置中的移动搜索、bonus search、read-to-earn、visual search 均关闭，因此未在本次启用。

## 已修复的两个问题

1. **V2EX 同次运行恢复**：provider 在真正发出领取请求后抛错时，适配器现在做一次 `read_only=True` 的余额核验，不再次领取。未发起写操作的错误及此前已处于 pending 的读取失败不会触发额外循环。一个针对不明确领取的冒烟测试验证只发生一次写意图和一次只读恢复；该修改尚未替换旧生产适配器。
2. **Hermes 日报路径**：现有日报脚本是指向 scripts 目录外的符号链接，新的 Hermes 路径检查自 9 月 30 日起拒绝执行。已安装为 scripts 目录内的普通文件，保持原配置和结果来源，使用 Hermes 用户及实际 `_run_job_script` 验证通过。原每日 10:30、现有 Telegram 运维 topic 和 job ID 保留；本轮没有发送额外消息，也没有把本次验收结果混入旧生产结果。

## 清理清单与依赖

下列六个来源仓库的锁定提交与本地 HEAD 一致，`source-lock.json` 列出的保留文件 hash 全部匹配。但来源代码保存完整不等于新入口已替代生产路径。

- `smzdm-checkin-ql`
- `v2ex-dailycheckin-ql`
- `aliyun-dev-checkin-ql`
- `laowang-checkin`
- `microsoft-rewards-snapshot`
- `epic-freebies-verifier`

另有 `qinglong-benefits-deployment-private` 和索引 `qinglong-benefits-automation`，共八个旧仓库。本轮未删除它们：青龙仍有六项启用的生产 cron，适配器/快照仍通过旧仓库路径挂载；CookieCloud 同步仍依赖青龙的环境变量 API；Hermes 日报仍读取旧部署的 manifest 和结果。

新仓库目前没有原生调度安装、自动 CookieCloud 同步、每日汇总接线；也没有京东入口，旧京东任务本来就处于关闭状态。中国移动仍按原要求跳过。

满足以下条件后才能清理：补齐 Epic 公共入口和现有 Rewards 范围；通过真实任务验收；迁移凭据同步、状态/未确认动作、每日汇总和调度；逐项停旧调度后切新入口，确认无双跑；最后备份并删除八个旧仓库及已无引用的部署文件/容器。青龙在这时可以作为已被替代的调度器移除。

现场结构化证据在 NAS 的 `/home/yuwk/benefits-review/acceptance-20261003/`；含会话的 runtime 位于仓库外的私有目录，不上传 Git。
