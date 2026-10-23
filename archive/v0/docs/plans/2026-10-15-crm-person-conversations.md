# 个人 CRM 实施记录

## 已批准范围

采集器 → 数据归档 ← API / MCP。仅微信私聊；Person 固定基本属性；Interaction 可关联多人，只有一份可编辑正文；附件保留；不实现 UI、AI 工作流、画像、提醒或评分。不复制到 Hub 通用记录。

- Person：name / aliases / relationship / contacts(type,value) / tags / notes。
- Interaction：person_ids / type / channel / date / started_at / ended_at / content / source / attachment_ids。
- 微信增量同步、按来源会话聚合，可配置间隔默认 30 分钟，跨日跨批次不断开；人工编辑后只追加新消息。
- 新对象有新聊天即创建；手动新增和来源绑定可用；不按姓名合并、不扫描通讯录补历史。
- HTTP / MCP 提供完整 CRUD、合并、绑定、分页搜索和附件读取；沿用既有读写认证。
- 简单迁移既有私聊及有效手工记录，排除群聊和泛化空内容；保留旧库备份，继续原水位。

## 关键决定

使用现有 PostgreSQL 和文件目录；新表使用 crm_ 前缀，旧表只供一次迁移与备份，不再写入或镜像。共享服务进程、OAuth 及非 CRM 来源保持原样。SQLite 用于离线行为测试，生产 SQL 另在 PostgreSQL 验证。

## 验收

多人共享正文；增量分段边界、跨日与编辑保留；来源身份隔离；删除与合并；附件缺失及补齐；API/MCP 读写权限一致；分页搜索；既有记录转换与去重；真实小范围采集到读取。

## 进度

- [x] 核对调用链、现有工作树及运行入口。
- [x] 新归档与 HTTP / MCP。
- [x] 微信输入、附件、日报消费者切换及移除自我镜像。
- [x] 一次迁移与文档。
- [x] 离线及 PostgreSQL 验证。
- [x] 真实数据迁移、运行切换、端到端验收（记录实际权限/环境限制）。

实现位置：本项目 .worktree/crm-person-design，分支 codex/crm-person-design。主工作树的未跟踪文件不属于本任务。


## 实施结果（2026-10-15）

- 业务实现：`apps/crm/src/personal_crm/archive`；HTTP / MCP 共用 Archive。新表 `crm_*`，同步回执不存第二份正文。
- 已切换 NAS 服务及两台 Mac 的微信任务，沿用既有认证、签名、文件目录和 checkpoint。旧 CRM 镜像配置已移除，其他来源任务状态保持。
- 迁移：78 人物、14,143 条私聊消息与 1 条手工记录，形成 1,298 条交互；跳过 13,773 条群聊或空洞旧记录。43 个已归档文件均存在且大小相符。
- 验证：32 项本地测试、PostgreSQL 归档及共享附件清理回归、日报 smoke、真实小范围采集到 MCP 读取；14,143 条消息正文逐条对账无差异。
- 真实采样使用已存消息的重复投递验证增量去重，不回填历史。切换后两个原采集任务的成功水位继续推进。
- 旧业务代码和测试删除，历史表与备份保留，未执行历史物理清理。没有开发界面。

部署、备份、实测证据和工作树差异见 [验收记录](../crm-archive-validation.md)。


## 独立仓库发布

已发布私有仓库 [personal-crm](https://github.com/ump45nose/personal-crm)，main 与 v0.2.0 指向 `2cc7b1f`。独立版本只包含人物、交互、附件、微信私聊采集和 HTTP / MCP，不导入 Hub，也不注册日报或其他宿主工具。CRM 主体后续维护以独立仓库为准。

发行物 wheel 和 sdist 已发布并下载回读；下载的 wheel 安装后独立网络 smoke 通过。Mac 完整测试 27 passed，Linux wheel 的 PostgreSQL/接口测试 19 passed。发布没有改变现有线上服务或采集任务；本目录仍是此前已部署的宿主集成版本。
