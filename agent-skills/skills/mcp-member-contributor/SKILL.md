---
name: mcp-member-contributor
description: 自动发现、准备、校验并提交 Model Context Protocol 官方社区贡献；用于积累和核验 ump45nose 的 MCP Member 贡献证据，不用于批量灌水或自动授予身份。
---

# MCP Member Contributor

按 `discover -> prepare -> submit` 执行。一次只处理一个命令。

脚本位于本 skill 的 `scripts/run.py`。执行前，将下列 `<skill目录>` 替换为本 `SKILL.md` 所在目录。

## 固定规则

- GitHub 登录必须是 `ump45nose`；不一致时停止。
- 一次最多返回 3 个候选；只使用 `selected`，不得自行复活 `top_blocked`。
- Issue 必须有 `help wanted`、`good first issue`、`ready for work` 或维护者明确请求。
- `needs confirmation`、公开安全事项、任意关联 PR、assignee 或作者已有实现均阻塞。
- `prepare` 成功后直接执行 `submit`；不得跳过账号、远端、重复项或 artifact 校验。
- 不推 upstream 或默认分支，不保存或显示 token，不批量评论，不自动索要 Sponsor。
- 安全问题只走私密报告；SEP、功能、schema、新 example 先走 Discussion/Issue。
- 公开内容必须保留脚本生成的 AI assistance disclosure。
- Member readiness 只是证据整理，不代表官方已授予身份。
- 命令返回错误、状态损坏或远端变化时停止，不要绕过检查。

## 1. Discover

运行：

```bash
python3 "<skill目录>/scripts/run.py" discover
```

需要扩展仓库时追加 `--allow-repo owner/repo`。`selected` 最多 3 项；`top_blocked` 只用于报告原因。

## 2. Prepare

对代码候选先运行：

```bash
python3 "<skill目录>/scripts/run.py" prepare --candidate <id>
```

脚本返回 `ready_to_edit` 后，仅在返回的 workspace 和分支中修改、测试。完成后运行：

```bash
python3 "<skill目录>/scripts/run.py" prepare --candidate <id> --summary "<摘要>" --tests "<验证>"
```

回复、Discussion 或私密报告必须通过 `--body-file <path>` 提供正文。记录完整 artifact 后立即进入 `submit`。

## 3. Submit

直接运行：

```bash
python3 "<skill目录>/scripts/run.py" submit --candidate <candidate-id>
```

Discord 由调用 agent 发送：首次 submit 取得交接正文；发送后用同一命令追加 `--external-url <消息链接>` 记账。

## Dry Run

在命令前加 `--dry-run`。Dry run 可以读取 GitHub，但不得修改状态、Git、GitHub 或 Discord。
离线演练时，`discover` 和 `prepare` 都追加同一个 `--input-json <path>`，因为 dry-run 不保存候选。

每次结束只报告：候选、实际改动、测试、公开动作、阻塞项和下一步。
