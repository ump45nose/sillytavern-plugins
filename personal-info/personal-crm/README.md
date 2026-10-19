# Personal CRM

保存人物基本资料，以及你与他们发生的交互。用户与 AI 通过 HTTP / MCP 查询和直接编辑同一份内容；微信采集器只追加新增私聊。

```text
微信采集器 → 人物与交互归档 ← HTTP / MCP ← 用户与 AI
```

- **Person**：名称、别名、关系、联系方式、标签和可读备注。
- **Interaction**：关联一个或多个人、日期/起止时间、类型、渠道、一份 Markdown 正文及附件。
- 连续私聊默认按 30 分钟间隔聚合，跨日、跨同步批次不断开；重复消息跳过，新消息追加，不覆盖已编辑正文。
- API 与 MCP 共用归档服务。无需 Personal Data Hub，没有日报、提醒、Fact、画像、评分或表现界面。

## 本机启动

需要 Python 3.12+ 和 uv。认证/MCP 复用固定版本的 `mcp-platform` 库；它是同账号下的私有 Git 依赖，需要现有 GitHub Git 访问权限。

```bash
git clone https://github.com/ump45nose/personal-crm.git
cd personal-crm
uv sync --locked
cp .env.example .env
```

在 `.env` 设置既有 PostgreSQL 的 `DATABASE_URL` 和 `CRM_API_TOKEN`。示例默认只监听 `127.0.0.1`，本机 MCP 使用显式开发模式；公网部署按 [部署说明](docs/deployment.md) 配置 OAuth。

```bash
uv run personal-crm migrate
uv run personal-crm-server
```

健康检查：`http://127.0.0.1:8080/healthz`；HTTP 前缀：`/api/v1/crm`；MCP：`/mcp`。数据库固定使用 PostgreSQL；附件在独立的 `data/attachments` 目录。

创建人物：

```bash
curl http://127.0.0.1:8080/api/v1/crm/people \
  -H "Authorization: Bearer $CRM_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"张三","relationship":"朋友"}'
```

这里的 `CRM_API_TOKEN` 是调用终端中的环境变量，值与服务配置一致。完整人物、多人交互、搜索分页、附件及 MCP 示例见 [使用说明](docs/usage.md)。

## 微信增量采集

在已获本机数据读取授权的 Mac 上，配置 `connector.env.example` 中的读取器路径、服务地址、采集令牌和稳定设备身份，然后运行：

```bash
CRM_ENV_FILE=/absolute/path/to/connector.env uv run personal-crm-wechat --watch
```

服务器的 `WECHAT_WEBHOOK_SECRET` 与采集器的 `CRM_WEBHOOK_TOKEN` 使用同一随机值。没有 checkpoint 的设备从启用时间开始；已有设备继续使用原 checkpoint、账号命名空间和媒体队列。采集器读取目录只为定位私聊，不导入通讯录人物。媒体采集及读取器要求见 [部署说明](docs/deployment.md#微信读取器与附件)。

## 开发

```bash
uv sync --locked --extra dev
CRM_TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest
uv build
```

测试使用 PostgreSQL 临时 schema，结束后删除测试 schema；不要将生产表作为测试夹具。运行包只包含当前归档模型，已完成的旧表导入器已移除。历史修整脚本位于 `checks/`，不进入服务进程。

[发布说明](CHANGELOG.md) · [独立发布记录](docs/plans/2026-10-15-standalone-release.md)
