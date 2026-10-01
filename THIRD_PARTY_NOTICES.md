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
