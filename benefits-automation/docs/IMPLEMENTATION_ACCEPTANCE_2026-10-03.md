# 轻量脚本实现与 NAS 验收 — 2026-10-03

本轮按每个平台独立脚本实施，调度、日报和 Telegram 留给 Hermes。该记录取代本日早期检查点，业务结果以真实平台读回为准。

## 已交付结构

- 平台自己的 `run.py` 声明参数、环境变量、超时与浏览器需求；公共 runner 不再维护平台配置表、模式分支或调度审批桥。
- 共用一次性运行、结果协议、账号锁、全局浏览器锁、超时和 Linux 后代回收。库不启动服务，HTTP 入口不加载浏览器或模型。
- CookieCloud 可选读取器按需解密，仅返回目标站点可用 Cookie；复用现有服务，没有新增同步守护进程。
- Rewards 补齐旧部署启用的八项 CLI 绑定、APP OAuth、保存新会话、动态服务动作和只读确认。
- Epic 公共入口使用原生 Camoufox、持久账号 profile、按需挑战 SDK 和 CPA 模型桥；不导入完整上游服务/调度/录屏。
- 六个平台各有 README、依赖与来源说明。账号状态、配置、凭据、原始网页和排查材料均在仓库外。

## 业务证据

以下 UUID 仅为执行身份，不含账号凭据。最新文件不能取代对应历史 run 的真实结论。

| 平台 / 操作 | 结果 | Run ID |
|---|---|---|
| SMZDM | 签到 complete；奖励 unknown；额外奖励不适用 | `5d596f20-d0dc-48c3-a943-c0c9aa1e8bd7` |
| V2EX | 今日签到/奖励 complete | `b584afa3-ab43-48c1-a08b-c8ea0732fb62` |
| Aliyun | 签到和待收积分 complete；默认社区连续奖励不适用；14 个无活动旧社区不适用 | `0b3eaf4a-bbba-4c62-8c78-517b133967f3` |
| Laowang | CookieCloud 会话、自动 tncode、提交及签到读回通过 | `a67626a8-481a-4cc4-adb5-9dc87d745a07` |
| Rewards full | daily、desktop_search、app_daily、app_promotions complete；punchcards、claim 不适用；more_promotions blocked；extra 未确认 | `d5924a17-a81a-4d9c-bd33-2243cb846dc5` |
| Epic | 当前免费促销全部经商店“已在库”确认，exit 0 | `ec8196b0-aba2-4da8-90ea-e6e0de2e5a78` |

Aliyun 修复了与固定 provider 不一致的表单提交，改为 JSON；使用新推送 CookieCloud Cookie 进行实测。明确无活动数据不再算失败，未确认的既有提交仍不靠“无活动”推断到账。

Laowang 实际成功响应是包含 `_ok` 的有界 token，旧适配器仅接受字面 `_ok` 会丢弃成功。已按实际 tn_code.js 格式核验，同时拒绝 `not_*`/`error_*` 和 HTML；不以验证码通过代替签到成功。

Epic 修复 Camoufox 不接受可见性检查的旧 timeout 参数，及商店 `/en-US/p/` 到 `/p/` 的 canonical 路径。当前账号已有促销游戏，因此本轮只证明账号恢复、促销清单、商店所有权和公开轮询入口；**未遇到新订单或 hCaptcha，不能声称真实下单/挑战已经验收**。模型桥通过实际 SDK 类型、配置模型名和 fixture HTTP 冒烟，没有为了测试调用付费模型。

## Rewards 的剩余结果

每日活动已经读回到 3/3，桌面搜索为 100/100，APP 签到为 1/1；已有额度不继续重复搜索。原 onboarding 没有分配、待收积分为空时明确不适用。

“探索必应”八项中，信用分任务已确认 10/10；健康、菜谱、游戏三个可用任务暂未确认到账，另四项为等级锁定。激活请求记录后不盲目重发；当前任务使用固定上游的最多十个主题查询，搜索前记录 intent，跨次调用不重复同一查询。每项的状态/原因写 `extra-status.json`，不含 hash、Cookie、原始响应。

验证中出现过 Bing 验证码，run `9ba0c61b-fa20-465a-9974-0ef026d39bde` 保留 captcha 障碍信息并退出；后续只读检查未再显示挑战。此处没有将暂时消失的验证码描述成已实现通用 Bing solver。最终 extra run `5e4bb72a-3f2a-48e9-8ba9-7fb4d820f0d4` 正常执行后返回 exit 3：健康、菜谱、游戏各完成上游的十个主题查询，仍未确认积分，原因保留 `offer_not_credited`。没有重复激活不明确的旧请求。未到账任务仍不算成功，full 不能宣称全量完成。

## 资源与检查

公开运行器保证同一 runtime-root 的浏览器任务串行，平台内部阶段也顺序关闭。空闲时脚本不保留进程；旧生产容器仍在，不能将新脚本不常驻误写成已经释放旧容器内存。

一次性 `/proc` 后代采样所得峰值：Epic 1557.6 MiB、Rewards extra 1520.8 MiB。指标是进程 RSS 相加，共享页可能重复计入，**不是物理内存/PSS 或硬内存限额**。浏览器多进程不代表多个并行浏览器。

按要求只做基本冒烟：六个默认离线入口、平台间浏览器锁、CookieCloud 站点过滤、Aliyun 提交读回、Laowang 回执、Rewards 元数据、Epic 可见性与模型桥，以及语法/diff 检查。未重复运行历史完整回归。

## 上线与清理

该早期实现验证当时尚未切换生产。随后用户同意将 Epic/Rewards 剩余问题留到实际使用中完善，生产 cron 与统一结果按 [生产迁移记录](MIGRATION_2026-10-03.md) 切换。业务限制不再作为延迟调度迁移的条件。

切换时按平台停旧任务、让 Hermes 调用新入口并读取对应结果，再验证生产运行与清理。不要同时保留两个签到调度，也不要先删旧账号状态。
