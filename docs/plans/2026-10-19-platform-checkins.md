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
| GLaDOS | platforms/glados、对应测试、平台说明及独立计划 | 无 | 待派发 |
| 影视飓风 | platforms/yingshijufeng、对应测试、平台说明及独立计划 | 共用 YYB 取码客户端；可先用模拟取码开发 | 待派发 |
| Olé | platforms/ole、对应测试、平台说明及独立计划 | 共用 YYB 取码客户端；可先用模拟取码开发 | 待派发 |
| 雨云 | platforms/rainyun、独立依赖锁、对应测试与说明 | 现有浏览器租约 | 待派发 |
| WorkBuddy 双版 | platforms/workbuddy、对应测试、登录/续期说明及独立计划 | 无 | 待派发 |
| 网易严选 | platforms/yanxuan、对应测试、现行接口核验记录 | 当前真实接口证据 | 待派发 |
| WeTalk | platforms/wetalk、对应测试、平台说明及独立计划 | 无 | 待派发 |
| YYB 共用登录能力 | common/wechat_code.cjs、对应测试、YYB 接入与部署方案说明 | 用户扫码用于真实验收 | 待派发 |
| 集成（本聊天） | 中央计划、公共运行器必要改动、来源与许可汇总、根 README、nas-cron-jobs 的包装/日报/部署清单 | 各平台交付 | 已建立工作区与计划 |

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
