# 新增七个平台自动签到

## 已确认范围

- 用户已授权从本聊天原生 fork 平台任务，并开始并行开发。没有依赖顺序的平台同时推进。
- 新增 GLaDOS、影视飓风、Olé、雨云、WorkBuddy、网易严选、WeTalk；WorkBuddy 同时覆盖国内与国际版。
- 初版实现签到、积分查询、签到直接发放的免费奖励；不实现盲盒、补签、兑换、视频奖励及复杂成长任务。
- WorkBuddy 国际版每日使用 hy3 发送一次 `only print:1`；不添加额外额度预算配置。模型请求成功与积分到账分开记录，不能因未即时到账重复发送。
- 影视飓风和 Olé 优先验证 NAS 自托管 YYB-Go-Enhanced，共用取码能力；code 一次性使用，商家会话按账号私有缓存。
- 沿用 Hermes 调度、平台一次性入口、common 运行/锁/结果、仓库外凭据和异常日报。schema_version 维持 1。

## 当前基线与隔离

- 创建时主线基线：`6f91b1195fdb17ebfa21ff07a5879ba8ffc30479`。
- 主聊天另有 Epic/Rewards 修复工作；本任务不得覆盖、回退或提交该工作及无关未跟踪目录。
- 集成工作区：`/home/yuwk/code/.worktree/benefits-checkins-integration-20261019`。
- 所有平台在独立 worktree 和 `codex/` 分支开发。优先使用原生 fork 的独立工作区；若工具工作区位置不满足项目约定，在聚合仓库 `.worktree/` 内创建自己的开发分支，并始终显式指定工作目录。
- 每个任务只提交自己的变更，不直接合并 main、不改生产调度或共享代理。真实浏览器验收必须遵循现有公共租约。

## 任务与文件所有权

| 任务 | 所有权 | 依赖 | 进度 |
| --- | --- | --- | --- |
| GLaDOS | platforms/glados、对应测试、平台说明及独立计划 | 无 | 真实认证通过、今日已签到，整理复核 |
| 影视飓风 | platforms/yingshijufeng、对应测试、平台说明及独立计划 | 共用 YYB 取码客户端；可先用模拟取码开发 | 真实签到 +10，重复运行通过 |
| Olé | platforms/ole、对应测试、平台说明及独立计划 | 共用 YYB 取码客户端；可先用模拟取码开发 | 空门店真实签到、状态 N→Y，积分无增量 |
| 雨云 | platforms/rainyun、独立依赖锁、对应测试与说明 | 现有浏览器租约 | 真实签到 +500、独立读回和重复运行通过 |
| WorkBuddy 双版 | platforms/workbuddy、对应测试、登录/续期说明及独立计划 | 无 | 国内 +100；国际单次请求完成、奖励待确认 |
| 网易严选 | platforms/yanxuan、对应测试、现行接口核验记录 | 当前真实接口证据 | 只读登录失效；现行签到接口缺少证据 |
| WeTalk | platforms/wetalk、对应测试、平台说明及独立计划 | 无 | 仅 Cookie 返回缺少参数；待成功客户端只读请求 |
| YYB 共用登录能力 | common/wechat_code.cjs、对应测试、YYB 接入与部署方案说明 | 用户扫码用于真实验收 | 扫码、双 AppID 取码、重启后取码通过 |
| 集成（本聊天） | 中央计划、公共运行器必要改动、来源与许可汇总、根 README、nas-cron-jobs 的包装/日报/部署清单 | 各平台交付 | 代码及真实包装复核通过；主线另有变更，未启用新定时 |

平台任务如需公共接口变化，在独立计划记录所需接口，不各自修改公共运行器或调度仓库。来源版本和许可在平台自己的 provider-source 或 upstream-contract 文件记录，最终由集成统一更新全局来源与许可文档。

## 接入约定

- 每个平台提供 `platforms/<platform>/run.py`，复用 `common.runner` 与 `Task`；不加 `--execute` 不联网。
- 每次调用只处理一个账号，使用不含邮箱的账号代号。凭据与缓存位于仓库外，平台仅接收其声明的环境变量或私有配置路径。
- WorkBuddy 增加 `--edition cn|intl`，两个版本使用不同账号代号与私有凭据。调度层以可选 `platform` 字段将作业键映射到平台目录，旧配置默认沿用作业键。
- 微信两平台使用 Node.js 业务适配器，共用 `common/wechat_code.cjs`。约定导出 `getCode(config, appid)`，config 为调用方已读取的私有对象 `{url, token, account}`；使用 YYB 标准 POST `/wxapp/getCode`，body `{ref: account, app_id: appid}`，认证为 Bearer token；返回仅包含 code 的字符串。客户端不维护商家会话、不输出 code、不复制账号数据库。连接、认证与无效响应错误使用稳定原因并由适配器映射到结果。
- 微信账号引用不等于两个商家各自的 openid；YYB getCode 不需要调用方自行推导商家 openid。Olé 业务登录后从真实响应取得商家身份与门店信息。
- 提交前保存 intent；响应不确定时通过只读查询恢复，不盲目重试写操作。签到已确认与积分未知应分别保留，未知数值用 null。
- 浏览器任务设置 `browser=True`，单账号、全局串行、受总超时和后代进程回收约束；不关闭 TLS 或 Chromium sandbox。
- 第三方仅取必要业务实现及依赖，固定提交/hash并保留许可归属；不导入其调度器、通知 SDK、代理池或独立看板。未知许可的完整上游保持外部引用，不直接批量复制进仓库。

## 参考来源

- GLaDOS：https://github.com/dff652/GLaDOS-Qinglong
- 影视飓风：https://github.com/smallfawn/QLScriptPublic/blob/main/wxapp/yingshujufeng.js
- Olé：https://github.com/smallfawn/QLScriptPublic/blob/main/wxapp/olecs.js
- 雨云：https://github.com/LeapYa/Rainyun-Qiandao
- WorkBuddy 国内签到/续期：https://github.com/Cat-zaizai/ZaiZaiCat-Checkin/tree/main/script/workbuddy
- WorkBuddy 国内免费奖励参考：https://github.com/88lin/workbuddy-auto-signin
- WorkBuddy 国际登录/活跃流程：https://github.com/autumnsentiment/workbuddy-helper
- 网易严选历史线索：https://github.com/zjk2017/ArcadiaScriptPublic/blob/main/BackUp/%E7%BD%91%E6%98%93%E4%B8%A5%E9%80%89.js
- WeTalk：https://github.com/ZenmoFeiShi/Qx/blob/main/WeTalk.js
- YYB：https://github.com/525815266/YYB-Go-Enhanced

## 验收与交付

- 各任务完成真实业务逻辑、与改动相称的离线测试、独立入口和说明，不交付空壳执行器。
- 覆盖登录失效、今日已签到、活动关闭、异常响应及提交后连接中断；验证不误报成功、不重复提交。
- 缺少真实凭据时继续完成不依赖账号的实现和测试，明确列出尚待扫码/凭据的联调步骤，不把源码检查或模拟测试声称为真实签到成功。
- YYB 验证区分服务可启动、扫码、两个目标小程序取码、商家登录及续期，不能以其他商家取码成功替代本次验收。
- 网易严选历史脚本仅作线索；没有当前接口证据时报告准确阻塞，不按旧接口猜测批量任务或假装已可签到。
- 平台交付包含分支/工作区、提交、关键接口、测试结果与未验证项。完成必要本地提交检查点，留待集成审查，不自动合并或上线。
- 集成核对主线变化、各平台改动归属、入口/结果兼容、WorkBuddy 双版不互相覆盖、YYB 故障聚合与日报行为；验收后逐平台启用生产任务。


## 原生 fork 派发记录

已从原聊天原生 fork 八个独立 session，并逐个下发平台范围、文件所有权、独立 worktree、必要接口与验收要求。`wait_threads` 首次快照确认全部为 active / inProgress，未报告启动错误。此状态只代表开发已开始，不代表功能完成或真实签到验收通过。

| 任务 | 分支 | 状态 |
| --- | --- | --- |
| [GLaDOS 自动签到开发](codex://threads/01a1532a-c968-7073-b858-4bd24c185f94) | `codex/benefits-glados-20261019` | 已派发，状态快照确认执行中 |
| [影视飓风自动签到开发](codex://threads/01a1532c-83a6-77e3-a7a7-0213b10d041a) | `codex/benefits-yingshijufeng-20261019` | 已派发，状态快照确认执行中 |
| [Olé 自动签到开发](codex://threads/01a1532c-8b2c-7043-8e41-5eeddf9dbe7e) | `codex/benefits-ole-20261019` | 已派发，状态快照确认执行中 |
| [雨云自动签到开发](codex://threads/01a1532c-9126-7c62-a384-0a27b035e492) | `codex/benefits-rainyun-20261019` | 已派发，状态快照确认执行中 |
| [WorkBuddy 国内国际版自动签到开发](codex://threads/01a1532c-981c-7e91-83bd-44779c4ce003) | `codex/benefits-workbuddy-20261019` | 已派发，状态快照确认执行中 |
| [网易严选自动签到开发](codex://threads/01a1532c-a0d6-7541-9b87-7daa131f8861) | `codex/benefits-yanxuan-20261019` | 已派发，状态快照确认执行中 |
| [WeTalk 自动签到开发](codex://threads/01a1532c-ab10-7af2-84e6-af064b128a97) | `codex/benefits-wetalk-20261019` | 已派发，状态快照确认执行中 |
| [YYB 微信取码共用能力开发](codex://threads/01a1532c-b351-7eb0-aec7-d956aacc7df8) | `codex/benefits-yyb-20261019` | 已派发，状态快照确认执行中 |

所有任务的工作区为 `/home/yuwk/code/.worktree/benefits-<platform>-20261019`，业务项目在其中 `benefits-automation/`。各 fork 会话保留原对话历史，已明确要求只在分配的工作区写入、只提交自身变更。

首次尝试应用自动创建 worktree 的 fork，仅返回排队标识 `client-new-thread:ccd08b9a-0f55-456d-a82c-829af1577c99`，尚未取得可派发的子 thread ID。实际开发使用已返回真实 thread ID 的原生同目录 fork，并在项目 `.worktree/` 预建隔离分支；上表八项均已成功启动。该排队请求未下发任何开发任务。

## 配置与真实验收（用户已要求执行）

- 已核对主线推进到 `66f0633`，保留主树仍在更新的 Epic 计划，独立集成主线后收取八个已提交交付；没有修改主工作树。
- 集成离线验证：Python 133 项通过、2 项依赖环境跳过；Node 80 项通过。雨云另以其真实依赖环境验证。离线通过不作为账号签到验收。
- CookieCloud 实时包含 GLaDOS、雨云及 WorkBuddy 双版登录 Cookie；WeTalk 未发现凭据。GLaDOS 仍需匹配的 UA，网易严选只有只读接口实现，不注册虚假的签到任务。
- 用户本轮授权配置并真实验收；YYB 按已核对固定镜像加入 automation 正式入口，只更新本服务。私有随机管理密码/协议令牌保存于 automation/env，SQLite 与微信身份持久保存在独立 data 目录；复用 favsync_default，宿主回环 33082，无新公网入口。
- 雨云与 WorkBuddy 原 fork 继续负责自己平台的现有 CookieCloud 会话复用、配置、真实验收及必要修复。所有浏览器共享原 runtime 的公共锁；原账号、旧任务、代理和生产结果保持各自归属。
- 本聊天负责 YYB 部署/扫码、微信两商家联调、其余凭据配置和公共集成。新增生产任务仅在真实验收通过后启用，待授权或接口缺失的任务保留明确状态。
- 最新 Mac 同步已读取（2026-10-19T09:10:58.009Z）；WeTalk 只有两个 Cookie，没有 localStorage 或客户端参数。其原 fork 继续只读核对，GLaDOS 原 fork 从实际 Mac Chrome 核对 UA。
- YYB 微信扫码已成功确认并持久保存；两个实际目标 AppID 都已取码、登录商家。影视飓风真实签到积分 0→10，run `4019fa56-316c-4d15-a223-2d3e0ab30610`；重复运行 `2049d203-dbb2-4a38-9e80-70c3f5c992ba` 保留完成、积分 10→10。Olé 初次因适配器多余的必填门店限制受阻，核对固定参考后已移除；空门店真实签到 run `995b5518-cbaf-413d-9422-07ac54b4c603`，官方 N→Y、积分 0→0，重复执行确认 already_complete。
- 实测凭据错误的共同原因是既有 `hermes-yuwk-access.service` 会持续恢复 Hermes/本机管理身份的命名 ACL，0600 立即显示为 0660。保留服务与授权；三个 Node 平台复用 `common/private_file.cjs` 核对普通文件、当前 owner、当前 group 和无 other/执行权限，支持本身份管理组；不放宽到任意组。新增 ACL 场景回归，与受影响平台合计 70 项 Node 测试通过。
