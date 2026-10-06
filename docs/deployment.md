# 部署与维护

## 当前 NAS 入口

| 入口 | 管理方式 | 持久化 |
| --- | --- | --- |
| 统一 API / CRM MCP | 原 `personal-crm` Compose 项目、`crm` 服务、18086 端口及公网 CRM URL | 原 OAuth 卷、统一 PostgreSQL、统一文件卷 |
| Health / AutoAccounting | 原 `health-webhook.service`，保留 8765 端口，使用 `90-personal-data-hub.conf` drop-in | 直接写统一 PostgreSQL |
| 周期采集 | `personal-data-hub-collectors.service` | 统一运行记录、提交水位和附件 |
| ShellCrash 原始计量 | 原 `shellcrash-traffic-collector.service` | 原流量 SQLite；同一生产者 |
| 独立用量 MCP | 原 `usage-monitor-mcp` 服务 | 原用量数据、OAuth 和配置 |

已复用现有 PostgreSQL、网络、Cloudflare 路由、Authelia 和持久卷。没有另建 PostgreSQL 或身份体系。主仓库的 `mcp.app.yaml` 是原 CRM 身份的当前部署清单；独立用量 MCP 的清单仍在 `apps/usage-monitor/`。

私有配置目录为 `/home/yuwk/.config/personal-data-hub`，容器只读配置位于其 `container/` 子目录。`personal-data-hub-assets` 是 `/vol1/1000/personal-data-hub/assets` 的绑定命名卷。生产密码和凭据不放入 Git，不在构建上下文中传递。

宿主采集器以原用户运行。Google 的既有凭据由隔离只读导出进程读取，只返回采集结果；未放宽原凭据目录权限。Plaud 官方 MCP 在专用 Python 环境运行，自有采集入口为 `agents/nas/plaud-sync.py`。邮件适配只调用现有邮件服务容器的只读函数，保留原授权、筛选和附件政策，不修改未读状态。

## 更新

```bash
uv sync --python 3.12 --no-dev
HUB_IMAGE=local/personal-data-hub:0.1.0-stage1 ./deployment/build-image.sh
.venv/bin/mcpctl plan personal-crm --source /home/yuwk/code/personal-data-hub --target nas
.venv/bin/mcpctl deploy personal-crm --source /home/yuwk/code/personal-data-hub --target nas
sudo systemctl restart personal-data-hub-collectors.service health-webhook.service
```

构建复用已锁定的公共 MCP 基础镜像，安装自有 wheel、PostgreSQL 驱动和独立用量库要求的锁定公共事件库。`uv sync` 先填充锁定 Git 缓存；也可通过 `HUB_EVENTS_SOURCE` 指定该事件库源码路径。构建必须通过 `uv pip check`。Docker 命令需当前操作账户已有的权限；若使用 sudo，需保留 `uv` 所在 PATH。既有部署模式复用当前镜像，因此首次切换镜像应先在原 Compose 项目更新 `crm` 服务，再由 `mcpctl` 记录和校验部署，保留其他服务。

观察采集：`hub status`、`systemctl status personal-data-hub-collectors.service`。运行日志只记录来源、数量和错误类别，避免输出消息正文、邮件内容及凭据。`partial` 表示存在已归档的历史异常片段，不代表所有来源失败。

## Mac 同步 Agent

在 Mac 克隆同一仓库至 `/Users/yuwk/WorkSpace/Code/github/personal-data-hub` 后运行：

```bash
/usr/bin/python3 /Users/yuwk/WorkSpace/Code/github/personal-data-hub/agents/mac/install.py
```

安装器复用 `com.yuwk.personal-review-skysight` 和 `com.personal-crm.wechat`。保留原 Python / ChatGPT Node 授权路径、设备身份、白名单和检查点；Skysight 间隔调整为 900 秒。执行副本继续放在原 Application Support 路径，来源和更新由本仓库管理。微信 `.env` 迁到 Application Support，保留原虚拟环境解释器，代码改为读取本仓库的 `apps/crm/src`。

Mac 先交付稳定闭合文件，再由 NAS 校验组合哈希并提交归档；收到提交回执后才更新水位。计数修复只发生在交付副本，原 metadata 与验证记录同时保存。缓存轮转不产生删除事件。客户端在 `apps/mac-client` 管理，复用这两个 Agent。

## Mac 客户端

`python3 apps/mac-client/install.py` 在 Mac 构建并安装到 `~/Applications/Personal Data Hub.app`，保留前一版本。客户端的 Keychain 凭据和 Application Support 连接设置位于仓库外；打开应用后可从菜单栏查看归档与请求同步，现有 Agent 的安装和更新仍由 `agents/mac/install.py` 管理。

NAS 在私有配置中增加 `hub_viewer_token_file`。容器目录中的对应文件只读挂载到 `/run/hub`；不替换原 `hub_api_token_file`、Health / 财务 token 或 OAuth。升级服务后执行 `hub backfill-previews` 补齐历史查看字段，新采集自动维护。客户端连接原 HTTPS 公网入口，无新域名或端口。

第二阶段镜像为 `local/personal-data-hub:0.2.0-mac`，原 `personal-crm` Compose 项目只替换 `crm` 服务镜像；新候选清单位于 NAS 私有运行目录的 `releases/personal-data-hub-stage2/compose.yaml`。

## AutoAccounting 接入

使用官方 AutoAccounting 的账单 Webhook 导出，无需修改或安装自建 APK。官方已在提交 `1210983f`（PR #1390）合入此功能，验收时核对的官方 master 为 `34b38f82`。手机端沿用原 HTTPS `/autoaccounting/v1/bills` 地址及 Bearer；聚合端保留 `BillInfoModel` JSON 请求和 HTTP 2xx 回执兼容。

官方导出读取 Synced、Edited、Wait2Edit 三种状态，不主动发出删除事件。缺失账单不能推断为删除。`hub-deletion-outbox.patch` 和构建回执仅保留为可选扩展资料，未启用，不属于验收或客户端安装前提。服务端显式删除接口继续保留。

## 备份与回退

`hub backup --destination PATH` 生成包含归档表、版本、墓碑、水位和 CRM 兼容表的事务一致 JSONL；文件目录另行备份。生产 PostgreSQL 同时沿用现有运维备份，不以 SQLite 替代。

迁移前的原 Compose、环境文件、镜像信息、旧 ShellCrash 入口以及已暂停 Hermes 作业清单保存在私有 `rollback/`。旧数据卷和源码目录未删除。回退恢复原服务时应先停止统一采集和新推送入口；切换后产生的 PostgreSQL 数据需另行处理，旧 SQLite 不是新数据的同步副本。不可丢弃墓碑后直接重放旧备份。

12 个旧个人复盘、邮件处理及 Plaud 转录作业已通过 Hermes 官方 CLI 暂停；其他作业保留。`legacy/` 不注册自动任务，避免迁移后出现两个生产者。
