# 独立 CRM 发布

## 目标与范围

将已验收的人物/交互 CRM 发布到私有独立仓库 `ump45nose/personal-crm`，作为可独立安装和运行的最小功能。保留增量微信私聊、附件、HTTP/MCP、现有 OAuth 基座及一次性转换；移除 Hub/日报/Google/Memos/事件/Fact/提醒/评分/表现界面。

本次仅发布源码与发行物，不改变正在运行的 NAS 服务、采集设备或旧工作区私有配置。

## 关键决定

- 源代码取自 personal-data-hub 的 `codex/crm-person-design`（fcada0a）；现有独立仓库本机历史保留，在 `codex/standalone-release` 工作树交付。
- 独立包使用 `CRM_API_TOKEN` / `CRM_VIEWER_TOKEN`，不读取 Hub 配置或导入其模块。
- 保留固定提交的 mcp-platform 认证库；不重写认证，不引入新用户系统。
- 新库只创建当前 crm_* 表，旧 revision ID 作为升级标记。旧数据转换通过表反射，不引入旧业务模型。
- GitHub 仓库维持个人数据项目的私有可见性，发布 v0.2.0 源码、wheel、sdist 与使用说明。

## 验收与进度

- [x] 核对目标仓库、旧工作区与发布权限。
- [x] 拆分最小运行包及配置、迁移、文档。
- [x] 在不安装 Hub 的环境安装、运行、执行 API/MCP 和采集到读取检查。
- [x] 发布 main、v0.2.0 标签与 Release，并回读实际发行物。

## 验证结果

- Mac 独立环境完整测试 27 passed；Ruff check / format 均通过。
- 实际 wheel 安装后确认没有 personal_data_hub 模块；独立 CLI 启动以及真实 HTTP / MCP 网络链路通过。
- Linux 全新环境安装实际 wheel，PostgreSQL/接口测试 19 passed；每个测试 schema 用后删除，未修改业务数据。
- Mac/Linux smoke 均验证模拟来源消息被接受、重复跳过、编辑后只追加新消息，以及多人交互和附件读写。此次没有向真实微信账号发消息，也没有重启现有采集。
- 新库测试证明只创建 crm_*，旧 003 数据库升级后原表内容保留，不重建停用业务表。
- 发行物：personal_crm-0.2.0-py3-none-any.whl、personal_crm-0.2.0.tar.gz；发布后下载实际附件，安装 wheel 并再次执行独立网络 smoke。

发布入口：[v0.2.0](https://github.com/ump45nose/personal-crm/releases/tag/v0.2.0)。原始本机仓库工作区和私有配置不变，当前发布源码位于 .worktree/standalone-release。
