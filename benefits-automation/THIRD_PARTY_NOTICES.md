# 来源与许可证

本仓库为私人迁移项目，不因汇总第三方来源而重新许可所有代码。

`upstream/` 中保留六项公开业务来源，许可证分别如下；每个目录保留完整原 LICENSE 与原作者署名，精确提交记录在 source-lock.json。这些原始文件只作归属/对照，不由新 runner 调用。

- SMZDM：smzdm-checkin-ql，MIT（原 LICENSE 署名 Hex）
- V2EX：v2ex-dailycheckin-ql，MIT
- 阿里云适配层：aliyun-dev-checkin-ql，MIT
- Laowang：laowang-checkin，MIT
- Epic 适配层：epic-freebies-verifier，GPL-3.0（保留原许可文本，不改为 MIT）
- Rewards 快照：microsoft-rewards-snapshot，GPL-3.0（保留原许可文本，不改为 MIT）

外部依赖由各自许可证约束：dailycheckin（MIT）、Playwright（Apache-2.0）及其传递依赖许可证随安装包保留。锁文件不替代许可证。

候选 Rewards 上游 TheNetsky/Microsoft-Rewards-Script v4.3.2 为 GPL-3.0-or-later；本仓库包含下述精确解析器与协议适配代码；保留 GPL 要求，不将这些来源误标为 MIT。

候选 Epic 上游 Ronchy2000/epic-freebies-helper 的 pyproject 声明 GPL-3.0-or-later；应用保留在外部受审阅目录，未复制进本仓库。具体来源组合及第三方模型/浏览器条款须在分发前逐项确认。

Aliyun 外部 daily.py 未发现 LICENSE，不在本仓库分发；精确字节 hash 仅作为本地依赖契约，不授予复制/分发许可。原始私有部署、旧容器定义、禁用 JD、队列 worker 和私人研究材料均不纳入发布内容。

Rewards activities.cjs 来自所有者私有 daily-activities.cjs 的授权重构，不冒称 GPL 快照来源；独立加载 Apache-2.0 的 patchright。原始私有部署整体未发布。

第二轮 snapshot.cjs 由已保留 GPL-3.0 快照来源改造，沿用其许可约束；extra.cjs 基于所有者私有 extra-activities.cjs。Rewards build.py 是固定源码的构建/入口补丁配方，完整上游及依赖留在外部目录，不在本仓库重新发布；使用/分发构建产物仍受其 GPL-3.0-or-later 与各依赖许可证约束。

Rewards vendor/rewards-parser 现在包含官方 v4.3.2 的精确 ReactFunc.ts、可重复构建的 ReactFunc.js/source map 和完整 GPL-3.0 LICENSE；上游 package 声明 GPL-3.0-or-later，PROVENANCE.json 固定来源与生成条件。没有改写解析器或误标 MIT。仅该无运行时依赖的解析器被分发，完整上游仍在外部开发目录。

Rewards server_actions.cjs、punchcards.cjs、app.cjs 的版本绑定协议改造源于同一官方 v4.3.2 BrowserFunc 与 activities/{api,rewards,app}，按 GPL-3.0-or-later 保留；完整许可位于 platforms/rewards/vendor/rewards-parser/LICENSE。goal.cjs 源于所有者私有 extra-activities.cjs 的授权重构。

## 2026-10-03 窄范围实现接入

Epic `native.py`、`model_bridge.py` 现在包含参考 Ronchy2000/epic-freebies-helper 的浏览器、登录和 OpenAI compatible 模型桥适配；依旧按 GPL-3.0-or-later 保留，完整许可在 `upstream/epic-freebies-verifier/LICENSE`，固定提交 `d90190bf3f9f87e9da71c50c81f155c4586bdb33` 由 `platforms/epic/upstream-contract.json` 指定。没有复制完整应用、settings、容器或调度服务。Camoufox、hcaptcha-challenger、Google GenAI 等可选安装包遵循各自原许可证。

Rewards `promotions.cjs`、`app_auth.cjs` 以及 `extra.cjs` 的探索激活部分，窄范围改造自 TheNetsky/Microsoft-Rewards-Script v4.3.2 的 URL 活动、积分领取、OAuth 与 SearchOnBing 协议，沿用 GPL-3.0-or-later，完整许可在 `platforms/rewards/vendor/rewards-parser/LICENSE`。本段取代前述“Epic 上游未复制”和仅 parser 被分发的旧检查点描述。

公共 Task 契约、CookieCloud 读取器为本项目新增代码；可选 cryptography 及传递依赖的原许可随安装包保留。CookieCloud AES 格式的互操作不改变服务本身或其许可。

## 2026-10-19 新平台

- WorkBuddy 的登录、刷新及国际活跃协议窄范围移植自 MIT 的 workbuddy-helper，原许可保留在 `platforms/workbuddy/LICENSE.provider`；对照的其他来源及固定提交在平台 `provider-source.json`。
- GLaDOS、影视飓风、Olé、WeTalk 根据公开协议独立实现，不复制未确认许可的完整第三方脚本；各平台 `provider-source.json` 保存精确来源、hash、证据和使用边界。网易严选只依据官方可观察接口实现积分查询，未复制官方前端资源或旧签到脚本。
- 雨云上游未发现 LICENSE，完整源码保持在聚合 Git 外；运行时只加载按 hash 校验的 ICR 算法与 stealth 文件。Selenium、OpenCV、Chrome for Testing 和 ChromeDriver 的原许可及 notices 随外部安装保留，专用依赖锁不授予再分发权。
- YYB 客户端为独立协议实现；YYB-Go-Enhanced 服务固定镜像和源码版本见 `docs/YYB_LOGIN.md`。服务镜像、完整上游和登录数据库不纳入本仓库，也不将其未知许可声明为 MIT。
