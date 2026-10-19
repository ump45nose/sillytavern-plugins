# Personal Records

个人信息统一 Webhook 收集端：接收来源原生报文，转换为业务记录并持久化，通过 HTTP / MCP 提供标准增删改查、筛选和汇总能力。当前支持 Health 与 AutoAccounting。

两个来源适配器共用 Webhook 接收层、SQLite 业务存储、HTTP 和 MCP。健康一天一条记录，账单逐张保存；无原始报文镜像、版本档案或自动归档文件。

## 运行

服务端 Python 3.12+，基础客户端兼容 Hermes 的 Python 3.11。独立环境安装服务器、测试和一次迁移依赖：

```sh
uv sync --extra server --extra test --extra migrate
.venv/bin/pytest -q
.venv/bin/personal-records serve
```

基础包包含业务模型、存储及纯标准库只读 HTTP 客户端；消费者安装基础包即可，服务部署安装 `personal-records[server]`。

服务器沿用 mcp-platform 的 `PUBLIC_BASE_URL`、Authelia OIDC、OAuth 存储和读写授权配置。无认证开发模式只能绑定回环地址。另配置四种不同凭据：`RECORDS_API_READ_TOKEN`、`RECORDS_API_WRITE_TOKEN`、`RECORDS_HEALTH_TOKEN`、`RECORDS_ACCOUNTING_TOKEN`。每种支持 `_FILE` 文件引用，不能同时配置明文和文件。秘密置于 Git 外。

`RECORDS_DATABASE` 默认 `/data/records.sqlite`。SQLite 使用 WAL；数据库与 OAuth 状态分别存放，不复制生产秘密进源码或镜像。

## 接口

- `POST /webhooks/health`、`POST /webhooks/autoaccounting` 接收原生 JSON，来源 Bearer 只能访问自己的接收入口；提交后返回 `ok/committed/created/updated/unchanged`。
- `/api/v1/health/days` 与 `/api/v1/bills`：POST 创建、GET 列表/详情、PATCH 修改、DELETE 删除。列表 `offset/limit`，默认 50、最大 200。
- `GET /api/v1/health/summary?start_date=2026-10-01&end_date=2026-10-31`：日期两端包含，可重复 `metrics` 参数选指标。
- `GET /api/v1/bills/summary`：同样的日期参数，支持 type/currency/category/book/account/account_from/account_to/status/query 筛选，`group_by` 为 date/month/type/currency/category/book/account_from/account_to。
- `GET /api/v1/sources` 返回最后成功接收时间。`GET /healthz` 检查进程与数据库。`/docs` 提供 OpenAPI；`/mcp` 提供 13 个 CRUD、查询、汇总和状态工具。

读 Token 可读；写 Token 可读写；MCP 使用公共运行时的 OAuth 读写权限。同一业务层产生两种接口结果。旧 Hub 路径不提供别名。

健康日记录以北京时间 `date` 为身份。步数/热量为日数值；心率、静息心率、血氧、基础代谢率、睡眠和运动为各自数组，记录时间统一 UTC。睡眠整段按来源会话结束日归属，阶段平铺，清醒阶段不计实际睡眠。来源提供的 origin/device 随测量项保存。缺失不补零。

Webhook 增量合并，按时间/区间、来源、设备更新同一项。公共 PATCH 替换指定数组，省略字段保持，null 移除指标。无原生样本 ID 时不能推断不同时间的样本是否是修订。删除后重新上传可重新创建；不保护人工修改免受后续来源更新。

账单本地 UUID 与来源身份分开。金额/手续费为十进制字符串；币种代码独立汇总；来源类型保留收入/支出/转账以及退款、报销、借贷、还款细分。默认汇总 confirmed，pending 数量单列，可显式筛选 pending。不自动换汇或把细分类型合并成净收支。

## 迁移与备份

```sh
personal-records migrate-hub --source-config /private/hub.json --database /private/candidate.sqlite --report /private/audit.json
personal-records status --database /private/candidate.sqlite
personal-records backup --database /data/records.sqlite --destination /private/backup.sqlite
```

迁移只读 PostgreSQL 一致快照，目的地必须不存在；只取当前 Health/finance 记录，不混合旧 SQLite/JSONL。独立磁盘审计索引逐个比较规范化业务字段和唯一样本，校验失败删除本次候选库。两个早期华为日汇总仅迁日期与步数，其余未迁字段在报告中计数，完整原件保留在历史备份。

备份使用 SQLite backup API，包括 WAL 中已提交数据，禁止直接只复制运行中的主文件。OAuth 状态按 MCP 平台方式配套备份。正式部署入口为 NAS mcp 组 Compose；私有数据、配置与源码分离。实施和验证见 [计划](docs/plans/2026-10-16-health-accounting.md)。

## 本机入口

正式公网入口为 `https://records-home.172906573.xyz:28443`：

- Health：`https://records-home.172906573.xyz:28443/webhooks/health`
- AutoAccounting：`https://records-home.172906573.xyz:28443/webhooks/autoaccounting`
- MCP：`https://records-home.172906573.xyz:28443/mcp`

沿用现有 Nginx Proxy Manager，域名转发到 `192.168.31.201:18087`，复用已有泛域名证书。公网 443 受限，URL 必须带 `:28443`。DNS 使用现有 DDNS 泛域名 A/AAAA，不新增此域名的 CF Tunnel/CNAME。

`mcp.app.yaml` 保存服务和 OAuth 元数据；此服务的域名由本机 NPM 管理，不执行会登记 Tunnel 的 `mcpctl deploy`。修改公共地址时同步服务环境和该独立 OIDC 客户端回调，保留密钥与 OAuth 状态。
