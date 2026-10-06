# Personal Review

Hermes 个人复盘系统的独立 Python 应用。它把 Skysight、邮件、Google Calendar/Tasks、健康、账单和 Git 汇总视为原始事实，把 Memos 视为唯一人工确认账本；USER.md、Mem0 和 Google Tasks 投影只消费确认后的内容。阶段模型固定为一条全局主线，领域只用于区分关联到该主线的阶段目标。

## 运行边界

- 应用部署目录：`/vol2/1000/Docker/personal-review`
- Hermes 薄 Skill：`profiles/lingjun/skills/lifestyle/personal-review`
- 真实凭据只通过 `REVIEW_*_TOKEN_FILE` 一类文件引用读取。
- SQLite 只保存 checkpoint、幂等键、冻结会话、投影 outbox 和附件队列。
- 所有外部副作用由功能开关控制；默认全部关闭。
- 日报将 Skysight 上游 6 小时 `Memory summary`、带标签 Memo 和结构化来源先组成固定 Markdown 分区；CRM 输入除关系变化计数外，还会读取按联系人去重且有界的内容摘要；LLM 只做轻量压缩、重点加粗与独立评论，不再生成自定义 Episode。
- Google 21:10 no-agent 输入只保存日历最小字段和当天已完成 Tasks；Mem0 不作为日报来源。
- Hermes 21:15 cron 使用 GitHub MCP 查询当前认证用户的当日提交，按仓库计数为一个 Git 区块；不扫描任何机器的本地仓库，也不把提交拆成日报候选。

## 常用命令

```bash
reviewctl config validate
reviewctl doctor
reviewctl cron diff
reviewctl cron apply --dry-run
reviewctl cron apply
reviewctl daily prepare
reviewctl daily refresh
reviewctl daily acknowledge --session-id daily:YYYY-MM-DD --delivery-id '<稳定投递标识>'
reviewctl weekly prepare
reviewctl stage prepare-close
reviewctl stage reconcile --dry-run
reviewctl projections pending
reviewctl projections sync-user-md --dry-run
reviewctl attachment pending
reviewctl retention plan
reviewctl annual prepare
```

日报、周报、阶段和年度的 `finalize/close` 只接受用户确认正文文件。健康和财务是日报自动填入字段；Git、CRM 和阶段目标只作为材料背景。
同日重复 `daily prepare` 只回放冻结材料；`refresh` 才会重读完整窗口并合并。日报来源 checkpoint
先写入 pending，只有 Hermes 投递成功后的独立回执任务才会提交。

Git 汇总由受管任务 `personal-review-git-2115` 固定调用 GitHub MCP 的 `get_me` 与
`search_commits`，再通过 `reviewctl git import` 保存仓库计数和有限提交主题，并以 `reviewctl git verify`
校验当日产物。MCP 失败由 `reviewctl git fail` 标记，不会伪装成零提交；提交正文、diff 和邮箱不会进入日报状态库。

Hermes 使用 MCP 2.x 时，如果缓存里的参数 schema 变成空对象，应用
`deploy/hermes-agent/mcp-input-schema-compat.patch`，再运行 `hermes mcp warm github` 并重启 gateway。
该补丁只兼容读取 `inputSchema`/`input_schema`，不会读取或打印 OAuth 凭据。

## 上线门禁

1. P0/P1/P2 可独立验收，不写日报终稿。
2. 新日报先连续 dry-run 三个不同日期并人工抽查噪声。
3. 通过后启用 `REVIEW_ENABLE_DAILY`，用 `cron diff/apply` 切换受管任务，同时人工暂停旧日报任务。
4. 新日报真实运行七天后才删除旧日报 cron 与 Skill。
5. 周报、阶段、USER.md、Mem0、Tasks 和附件依次启用；任何投影失败都不能回滚已确认 Memos。

投影 worker 只会返回已启用 destination。`REVIEW_ENABLE_USER_MD`、`REVIEW_ENABLE_MEM0`、
`REVIEW_ENABLE_TASKS` 可独立启用；Mem0/Tasks 成功必须保存真实外部 ID，失败按 YAML 退避重试。
附件 worker 使用稳定附件 ID，超过 30 天仍未完成的项目进入人工清单。Raw 到期后先进入
7 天压缩隔离区，derived 只有在对应年度总结已确认后才归档。

## 回滚

- 先关闭对应 `REVIEW_ENABLE_*`，执行 `reviewctl cron diff` 确认，再 `cron apply`。
- Memos 升级回滚必须同时恢复旧镜像、本次完整数据库/WAL/附件备份。
- 不直接编辑 Hermes `jobs.json`；所有受管调度都通过 Hermes CLI 更新。

## FnOS 升级后的权限修复

FnOS 升级或在 NAS UI 中修改 `Docker` 目录权限后，父目录 Trim ACL 可能覆盖项目内的 POSIX 权限。
使用 root 运行 `deploy/fix-permissions.sh`：脚本会先备份 ACL 元数据，再让静态代码由 `yuwk`
维护且对 Hermes 只读，让 `data/state/logs/tmp/artifacts` 同时允许 Hermes 运行和 `yuwk` 维护，
并保持 `.env` 为 `hermes:hermes 0600`。脚本不会读取或复制 `.env` 内容。
