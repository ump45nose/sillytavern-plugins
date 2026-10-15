# Personal CRM

以人物为入口，保存你与他们发生的交互。用户与 AI 通过同一套 API / MCP 读写；微信采集器只同步新增私聊。

## 结构

采集器 → 数据归档 ← API / MCP。服务端与现有 Hub 共进程、共 PostgreSQL 和附件目录；CRM 使用独立的 `crm_*` 表，不复制到 Hub 的通用记录、版本或展示索引。

- **Person**：名称、别名、关系、联系方式、标签、备注。
- **Interaction**：一个或多个人、发生日期/起止时间、类型、渠道、一份可编辑正文、来源及附件。
- 微信连续私聊聚合成一条交互；原文和手工记录都可直接编辑，后续只追加新消息。
- 不提供 AI 审批、画像、提醒、关系评分或自动发送。

## 开发与验证

在仓库根目录执行 `uv sync --all-packages --all-extras --python 3.12`，然后执行 `uv run pytest apps/crm/tests`。
生产使用 PostgreSQL；测试可使用 SQLite，设置 `CRM_TEST_DATABASE_URL` 可将归档行为测试运行在 PostgreSQL 的临时 schema 内。

数据库先执行 `personal-crm migrate`。旧数据转换执行 `personal-crm migrate-legacy`，只允许在新归档为空时执行一次，不重新采集微信历史。

[读写与查询示例](docs/usage.md) · [部署与迁移](docs/deployment.md) · [插件接入](docs/plugin.md)
