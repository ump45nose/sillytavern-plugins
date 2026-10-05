# 公共获取宿主部署与迁移记录

2026-10-04 已部署独立公共宿主及两个入口，完成旧配置、记录迁移并恢复片单调度。
部署时出现的 TMDB TLS 握手 `UNEXPECTED_EOF_WHILE_READING` 已修复，真实媒体识别与两站查询通过。
部署期间仅验证鉴权、回执读取、协议与搜索；之后按用户指令完成[一次真实查询与下载提交验收](acquisition-real-download-2026-10-04.md)。

## 运行入口

| 服务 | 地址 / 运行方式 |
|---|---|
| 查询网页 | `http://192.168.31.201:8090`，同时保留本机回环绑定 |
| 下载 MCP | `https://media-download-home.172906573.xyz/mcp`，宿主仅绑定 `127.0.0.1:8091` |
| 公共宿主 | MoviePilot 插件 `MediaCapabilities 0.1.1`，已启用 |
| 片单 | `FilmWatchlist 1.4.2`，恢复原正式模式、360 分钟调度，未立即执行扫描 |

网页和 MCP 由仓库根目录 Compose 管理，更新时只指定相应服务：

```sh
docker compose -f /home/yuwk/media-automation/compose.yaml up -d --no-build media-search media-download-mcp
```

原 MCP 的 `media-download-mcp.service` 已停止并禁用，保留单元及备份供入口回滚。
公网域名、访问令牌及共享 Tunnel 路由保持一致；公共部署 CLI 验证配置无需变更。

## 配置和持久化

- MoviePilot 保留现有 `local/moviepilot-media-tools:2.14.2-20261003` 镜像。
- 共享 wheel `0.3.1` 通过宿主 Python 安装到 `/config/media-capabilities-runtime/0.3.1`，Compose 的 `PYTHONPATH` 指向此持久目录；旧 `0.3.0` 目录保留。
- 两个插件运行副本保存在 `/config/plugin-runtime` 并挂载到 MoviePilot 插件目录；本地安装源仍位于 `/config/local-plugins`。
- 网页配置与秘密：`/home/yuwk/.config/media-automation/media-search`。
- MCP 配置与秘密：`/home/yuwk/.config/mcp-platform/media-download-mcp`。
- 秘密文件权限 `0600`，不进入源码或构建上下文；网页与 MCP 使用各自访问令牌，MoviePilot 后端令牌仅保存在服务端。
- 保留当前 MoviePilot JWT 签名密钥并写入原 `app.env`，未轮换密钥；后端 Bearer 令牌有效期一年，已验证新 Python 进程可使用持久化密钥校验。

公共宿主继承 M-Team 站点 ID `1`。首次部署保留原 115 开关；后续按用户指令
将公网 BT 路由启用为 115，新增“自动下载仅公网资源”并保持关闭，115 分享继续关闭。
浏览器会话与 Relay 文件路径保留；新设备凭据只写入受保护文件。

## 迁移和验证结果

- 25 条旧片单记录与迁移前内容一致；4 条旧下载回执及资源哈希已登记到公共宿主。
- 首次迁移标记完成，重复初始化不覆盖新配置或重新提交；新增下载提交为零。
- MoviePilot 新接口：匿名 `401`，Bearer 回执查询正常。
- 网页：页面和健康检查 `200`，匿名业务请求 `401`，登录后读取宿主回执正常。
- MCP：本机及公网匿名拒绝、initialize、三个工具枚举通过；容器内后端 Bearer 回执查询通过。
- 真实搜索：TMDB `278` 识别为《肖申克的救赎》（1994）；M-Team 与 Mini4K 均返回 `OK`，合计 161 个候选，首批结果约 4.3 秒，两站首批查询完成约 14 秒。未调用下载或候选预检接口。
- 后续真实下载验收：公网 MCP 均衡策略选择 2160p BluRay x265 的 22.48 GiB MKV，经 MoviePilot 提交默认 qBit，返回 `submitted`；网页复用相同请求 ID 未重复入队。新增一个下载任务，公共宿主保留一个新增资源登记。传输状态及降级说明见独立验收记录。

## TMDB TLS 修复

2026-10-04 22:54（北京时间）完成分流修复。原 TMDB 连接经 `🌐 国际服务 → 🏢 机房稳定` 的美国 DMIT 出口，在 TLS 握手阶段被关闭。
使用 Mihomo 单节点延迟接口对同一 HTTPS 地址进行对照，原出口失败，现有日本自动出口成功返回预期的未鉴权 `401`。
随后通过[官方配置重载接口](https://wiki.metacubex.one/en/api/#configs)应用两条域名规则：

```yaml
- DOMAIN-SUFFIX,themoviedb.org,🌊 廉价自动
- DOMAIN-SUFFIX,tmdb.org,🌊 廉价自动
```

规则保存在 `/etc/ShellCrash/yamls/rules.yaml`，ShellCrash 启动及订阅更新时会合并到运行配置。
配置已通过 CrashCore 校验，重载返回 `204`，其他手动分组选择保持一致。
MoviePilot 的代理地址、镜像及 TLS 证书校验配置未修改；无需重启 MoviePilot。
容器内带正常 API 鉴权访问 TMDB 返回 `200`，随后通过网页后端完成上述真实搜索。

代理修改前的运行配置、自定义规则及验证记录保存在权限受限的
`/etc/ShellCrash/backups/tmdb-tls-20261004T145444Z`，其中配置含秘密，不应公开。
回滚时仅移除这两条规则并重新合并、重载；完整备份仅用于对照，避免覆盖后续代理调整。

## 备份和回滚

MoviePilot 备份目录：
`/vol2/1000/Docker/moviepilot/config/backups/media-capabilities-20261004T133600Z`。
包含原插件配置及记录、SQLite 一致性备份、原 Compose、原插件副本和迁移结果。
MCP 原 systemd 单元及配置备份位于其私有运行目录的 `backups/20261004T133600Z`。

构建源码摘要、镜像 digest 和部署记录位于仓库 `.build/deploy-capabilities/20261004T133600Z`。
源码来自当前工作区，未将未提交改动声明为已发布版本。

回滚先停止新提交，再恢复本次运行配置或入口；公共提交登记和业务记录继续保留。
不要恢复整个旧数据库覆盖后续业务写入；旧版片单在公共宿主恢复前保持暂停，避免绕过去重。

## Mini4K 与下载配置更新

跨至 2026-10-05 的修复完成 Mini4K 空搜索页识别及 Browser Relay 标签复用，
启用公网 BT → 115 的默认路由，并新增仅限制自动下载的公网开关。
当前版本和配置见上表；两个入口仍使用兼容的原应用镜像。
详细问题、验证及备份见[Mini4K 修复记录](mini4k-public-only-fix-2026-10-05.md)。
