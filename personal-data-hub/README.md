# Personal Data Hub

保存确实需要补同步、补持久化或自行处理的数据：微信对话、Skysight 电脑历史、Plaud 音频和转录、健康、账单、网络流量。服务端复用现有 PostgreSQL 和附件目录，提供原件、阅读内容与同步状态的只读查询。

## 当前范围

| 来源 | Hub 的职责 | 当前实现 |
| --- | --- | --- |
| CRM / 微信 | 将 Mac 对话按联系人或群聊可靠归档 | 保留 webhook、跨设备消息去重、附件及同事务归档；业务表精简另行设计 |
| Skysight | 同步仅在 Mac 保存的活动片段和已有摘要 | 文件校验、提交回执、原始片段与摘要归档 |
| Plaud | 下载音频并取得自有转录文本 | 保留既有独立转录任务、原音频、转录 Markdown 和处理状态 |
| Health | 为手机上传的健康数据提供长期存储 | `/health/import`、幂等上传及历史读取 |
| AutoAccounting | 为手机账单提供长期存储 | 官方账单 webhook、按源 ID 更新及显式删除 |
| 网络流量 | 采集并持久化 NAS / Mac 代理统计 | 小时累计事实、设备边界、缺口和提交回执 |

Mem0、Hermes 报告不再采集。Memos、GitHub、Emby、Navidrome、Google Calendar/Tasks、Token Monitor 和邮件退出 Hub 的采集、镜像、加工和展示链路；这些原系统继续维护自己的存储、接口与独立任务。Hub 不再依赖 `usage-monitor-mcp`。独立用量服务源码仍在 `apps/usage-monitor`。

历史镜像、附件、任务和水位保留；默认来源、列表、阅读搜索和统计仅包含保留范围。历史原件及已发布内容可凭原 ID 显式读取。已退出来源无法重新注册或通用入库，旧任务不会被领取，回填不再处理其原件。物理数据清理需要独立列出对象和影响，本次不执行。

## 数据与运行

当前原件仍存在 `hub_records`，包含稳定来源身份、原始载荷、适配字段、时间和附件引用；版本在 `hub_revisions`，阅读内容在 `hub_content_*`。结构重设计不在本轮来源清理中执行。

结构化数据使用独立数据库 `personal_data_hub`；文件按 SHA-256 存在 `/vol1/1000/personal-data-hub/assets`。设备身份、凭据、配置、数据库和附件均在 Git 外。显式删除保留墓碑，阻止旧备份重新导入已删除数据。

2026-10-13 止血措施继续保留：`personal-data-hub-collectors.service` 停止并禁用，后台轮询和阅读加工暂停；微信、健康、账单、设备推送与显式文件确认入口保留。来源清理不会自动恢复后台。现有部署仍是 0.4.9，清理分支在完成主工作区归并前不部署。见 [止血记录](docs/performance-relief-20261013.md) 和 [清理计划](docs/plans/2026-10-15-source-cleanup.md)。

## 维护

每个 worktree 独立安装依赖，不复用可写虚拟环境：

```bash
uv sync --python 3.12 --no-dev
.venv/bin/hub status
```

默认私有配置为 `/home/yuwk/.config/personal-data-hub/config.json`，可用 `HUB_CONFIG` 或 `hub --config PATH` 指定。参考 [配置示例](deployment/config.example.json)。旧配置含已移除适配器时会明确拒绝启动，先生成独立候选：

```bash
.venv/bin/python deployment/cleanup-source-config.py \
  --config /path/to/private/config.json \
  --output /path/to/private/config.candidate.json
```

候选只移除退出来源的配置条目，不改变剩余来源、秘密、暂停状态或持久数据。宿主和容器配置都要处理；候选替换与目标镜像更新一起执行，不能把旧配置直接交给新版本。

只读入口包括 `/api/v1/records`、`/api/v1/contents`、`/api/v1/sources`、`/api/v1/network` 和既有 `/mcp`。API Bearer、只读查看凭据与 OAuth 分开管理，沿用现有身份。列表只返回有界预览，完整正文、附件和依据按需读取。

## 源码边界

- `src/personal_data_hub`：保留来源的适配、归档、加工和查询。
- `apps/crm`：微信接收、既有 CRM 业务、OAuth/MCP 和聊天事件。
- `agents/mac`、`agents/nas`：设备同步与流量采集。
- `collectors/plaud`、`processors/plaud`：音频同步和独立转录处理。
- `apps/mac-client`：由用户在 Mac 修改，本轮只交付 [客户端接口调整清单](docs/client-requirements/source-cleanup.md)。
- `legacy`：历史源码，不注册采集任务。

正式 NAS Compose 仍为 `/vol2/1000/Docker/stacks/mcp/compose.yaml` 的 `crm` 服务。构建用 [deployment/build-image.sh](deployment/build-image.sh)，只打包 Hub 和 CRM。保留原 OAuth 状态、1000:1001 身份、持久卷、域名与网络。具体操作见 [部署说明](docs/deployment.md)。
