# 独立部署

一个 `personal-crm-server` 进程连接既有 PostgreSQL，使用自己的附件和 OAuth 目录。容器不安装 Hub，也不挂载 Hub 配置或资产目录。

## 配置和启动

复制 `.env.example`，设置 `DATABASE_URL=postgresql+psycopg://...`、`CRM_API_TOKEN`、可选只读 `CRM_VIEWER_TOKEN`、`WECHAT_WEBHOOK_SECRET`。配置文件仅供运行账号读取。启动不自动迁移：

```bash
uv sync --locked
uv run personal-crm migrate
uv run personal-crm integrity
uv run personal-crm-server
```

- 分段间隔 `WECHAT_INTERACTION_GAP_MINUTES=30`，修改只影响后续采集。
- 公网 MCP 关闭开发模式，配置公开 URL、OIDC 和现有 OAuth 凭据。
- `OIDC_READ_ONLY_USERNAMES` 不会升级为写权限；复制部署时保留原 OAuth 状态目录、签名/存储配置及 `personal-crm-oauth-v1` 格式。
- 反向代理转发整个服务，包括 `/mcp`、`/.well-known/*` 和 OAuth 路由。
- 业务内容和附件按普通文件保存；OAuth 凭据存储沿用既有认证库。

数据库基线为 `004_person_archive`。新库只创建当前 `crm_*` 表；已在该 revision 的库无需再导入。001–003 的旧模型导入已完成，不再保留长期转换入口。备份使用 PostgreSQL `pg_dump`，附件和 OAuth 目录分别备份；回退软件不能覆盖切换后新增的数据。

## 容器构建

需要 uv，以及对固定版本 mcp-platform 源码的访问权限。它是通用认证/协议库，不是运行服务。

```bash
uv build --wheel --out-dir dist/wheels
uv export --frozen --no-dev --no-emit-project --no-emit-package mcp-platform \
  --no-hashes --format requirements-txt > dist/requirements.txt
# 在固定 revision dea309a5d83b6365a57937bc6e11affe692bfcaf 的 mcp-platform checkout：
uv build --wheel --out-dir /absolute/personal-crm/dist/wheels /absolute/mcp-platform
# 回到 personal-crm：
docker build -t local/personal-crm:0.3.0 .
```

使用 `compose.yaml`，将 `server.env` 配好并接入能访问现有 PostgreSQL 的网络。先在独立端口检查健康、认证、读取与附件，再切换反向代理。原宿主的其他数据来源保持原入口。

## 微信读取器和附件

采集器在获授权的 Mac 上使用已有 `chatlog-keeper`。它提供 `directory --source wechat` 和 `message-stream-v1 --selection-stdin`。保留 `CRM_CLIENT_ID`、`CRM_ACCOUNT_NAMESPACE`、`CRM_CHECKPOINT`、现有数据库读取授权和账号身份；不靠备注名识别人物。

```bash
uv pip install -r requirements-wechat-media.txt
CRM_ENV_FILE=/absolute/connector.env uv run personal-crm-wechat --watch
```

将 ffmpeg 放在 PATH（原生打包版本置于读取器旁的 bin 目录）。采集器只读已有数据库 key 缓存；微信图片缓存就地转换为 JPEG/PNG，SILK 语音转 WAV，普通文件原样归档。不做 OCR、转写或进程密钥扫描。账号统计文件不可用时可配置本账号 `WECHAT_IMAGE_UIN`，不保存图片密钥。

文件暂时未下载时保留元数据和稳定引用，读取明确返回 `available=false`。成功提交批次后才推进消息水位；媒体工作独立重试，不阻塞文字，不保留第二份正文。损坏 checkpoint 报错，不当成首次启用重置。

## 一次性历史修整

`checks/repair_archive.py` 清理机器生成的姓名/发言人和重复占位；`inspect-wechat-files.py` 从已保存消息定位文件元数据；`repair-wechat-media.py` 沿原上传入口补文件；`repair-media-files.py` 将旧附件缓存转为可打开文件并保留附件 ID。这些只在维护环境运行，输入、受影响行备份、报告保存在私有目录，不进入运行包。

修整不重抓全部聊天、不重新生成正文、不推进文字水位；已有人工编辑保留。旧历史物理清理独立处理。
