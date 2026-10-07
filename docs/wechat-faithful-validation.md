# 微信忠实采集修复与验收（2026-10-07）

原连接器只读取配置中的四个私聊，将正文改成泛化互动描述。NAS 的 8,803 条微信互动中，7,093 条只有泛化描述，1,710 条带旧正文前缀；原始消息 JSON 和微信附件均未归档。

## 当前行为

默认 `CHATLOG_SCOPE_MODE=all`，动态枚举本机单聊和群聊，按 reader 每次最多 128 个会话分块读取。会话类型以微信 ID 的 `@chatroom` 后缀确定，目录误标保留为来源元数据。`all_direct` 和 `configured` 仍可显式选择。

`interactions.message` 与 Hub 的 `raw.message` 保存相同的账号命名空间、会话身份、类型和完整 reader `record`，包括正文、时间、消息类型及发送者字段。JSON 原文保留空白和 NUL；兼容 Text 摘要移除 NUL。Fact 抽取关闭，没有启用 ASR 或模型处理。

Webhook 每片最多 500 条，最后一片确认后提交本地水位。旧互动按来源事件或稳定消息身份补齐，保留 ID 和删除墓碑。定时任务追平后按配置周期轮询。

Mac 客户端 0.3.0 build 7 直接读取 `raw.message.record.content`，微信详情按纯文本显示完整正文；原始 JSON 导出保留完整数据。原签名身份、Keychain 凭据和固定凭据助手保留。

## 真机回填与对账

本机会话目录为 2,029 个单聊、33 个群聊。原配置时间窗从 2026-06-06 至 2026-10-07 12:58:55（Asia/Taipei），reader 输出 24,934 条消息，涉及 95 个有消息的会话：单聊 12,013 条，群聊 12,921 条。

| 结果 | 数量 |
| --- | ---: |
| 新增互动 | 17,198 |
| 补齐旧互动原始消息 | 7,734 |
| 删除墓碑阻止重新导入 | 2 |
| 具有完整 reader 消息的归档 | 24,932 |
| 保留原 ID 的旧互动 | 8,803 |

源清单仅包含身份键和哈希。全部 24,932 条有效消息的正文及完整消息 JSON 哈希均与 NAS 相同，Hub 镜像逐条相同；单聊、群聊各取一条通过真实 viewer 鉴权详情接口验证。原 29 个墓碑和 12 条历史 Fact 保持原样，本轮生成 Fact 为 0。

Agent 恢复后，Mac 与 NAS 水位从 04:58:55 UTC 推进至 05:07:34 UTC，并新增一条真实消息，完整消息归档数变为 24,933；错误日志为空。

## 完整性边界

reader 的目录计数为 28,265 行，计数覆盖全部消息表行；流接口按时间筛选并忽略无法提取出内容的行。额外读取 1970-01-01 至 2026-06-06 的全部会话成功完成，输出为 0。目录计数与流输出的 3,331 条差额没有逐行归因，不能把目录总数当成已归档消息数。

仍有 1,069 条旧互动没有匹配到本轮来源身份，原记录继续保留；其中 758 条仍是泛化描述，311 条保留旧正文兼容字段。不能宣称这些历史记录已经补齐，也不能仅凭人物和时间相近合并消息。

文字回填保存的是 reader 返回的消息数据。图片、语音、视频等占位内容和元数据不等于历史媒体文件已下载；历史媒体不回填，也不能恢复本机已不存在的聊天正文。

## 后续媒体采集

`WECHAT_MEDIA_ENABLED=true` 启用独立持久队列，首次启用时保存 `enabled_since`。只为此后收到的图片、语音、视频和文件消息入队，不重置文字 checkpoint、不回填历史媒体。队列路径由 `WECHAT_MEDIA_QUEUE` 指定，默认在正文 checkpoint 旁；原文件先以 SHA-256 保存到私有 spool，再复用微信 webhook 令牌流式上传。文件晚到、网络失败或数据库缓存 key 不可用时按 1 至 60 分钟间隔重试，正文继续同步。后台最多运行一个媒体 worker。

- 图片：按 `attachment_meta.file_md5` 精确关联本机 `.dat`，保存原始加密字节，类型为 `application/vnd.wechat.encrypted-image`。用户选择暂不提供图片密钥；没有自动提取或生成密钥，也没有图片解密或 OCR。
- 语音：按 `server_id`、原生会话 ID 和时间查询本机 `media_N.db` 的 `VoiceInfo` / `Name2Id`。保留原格式，本机 SILK 保存为 `.silk` / `audio/silk`；其他原始字节保留为二进制，不转写、不转码。
- 视频：按消息元数据 MD5 匹配本机 MP4。文件：按原名称、字节数及来源提供的 MD5 校验。只读取消息明确关联的文件，不按时间相近猜测、不抓取 CDN。

媒体只绑定已存在的原消息，保持 Interaction ID 和完整消息 JSON。重复上传按文件 SHA-256 去重；正文重放和周期 CRM 对账保留已补齐的附件，删除墓碑拦截迟到上传。未下载、缺少定位信息或无法被动解密的媒体保留待重试状态，不能视为已归档。

本机只读验证确认 164 条语音均能通过 `Name2Id` 精确关联会话，并成功暂存一份 16,078 字节的原始 SILK，未上传历史媒体。新增媒体 HTTP、队列和 reader 测试及文字受影响路径合计 56 项通过，包含鉴权、哈希、幂等、墓碑、正文重放保留附件、未来时间边界、断网及源文件消失后的 spool 重试。测试使用合成附件，不修改生产聊天数据。

## 校验和部署

- CRM 受影响路径 49 项测试通过，`ruff --select F` 与 `git diff --check` 通过。PostgreSQL JSON 的 NUL 往返在回滚事务中验证。
- Mac 8 项测试通过，包含原文空白、NUL、超过 5 万字、空正文及旧记录兼容；release 构建、签名验证、真实客户端读取和附件哈希冒烟通过。签名 requirement 和凭据助手二进制哈希前后相同。
- NAS 镜像为 `local/personal-data-hub:wechat-faithful-2ba5c0e`，服务 healthy，健康及 OAuth 发现接口 200，匿名 MCP initialize 401。原 Compose 项目、端口和全部挂载保持原样。
- 生产数据库没有 `alembic_version` 表，本次只执行 `ALTER TABLE interactions ADD COLUMN IF NOT EXISTS message JSON`；没有重跑初始迁移。

数据库修改前完成 custom-format dump，大小 451,655,570 bytes、TOC 72 项，SHA256 为 `1d7b70fd278917ac49847c626f255e251a3e3a00b4c8a728ac4c65e070e83f1c`。NAS 数据库备份、原 Compose、部署和对账收据位于 `/vol1/1000/personal-data-hub/backups/wechat-repair-20261007-124730`。

Mac 原环境、停止后的 checkpoint 和 launchd 配置备份位于 `~/Library/Application Support/personal-crm/backups/faithful-repair-20261007-125526`；查看端安装前副本位于 `~/Library/Application Support/PersonalDataHub/backups/wechat-viewer-20261007`。完整回填使用独立 checkpoint，全部确认和对账通过后才原子交付给原 `com.personal-crm.wechat`。

回退只恢复旧镜像或已备份客户端，保留当前数据、OAuth 和设备授权。`message` 列是兼容的新增列，不应删除已回填数据或恢复旧 checkpoint 来覆盖成功水位。备份、来源清单、聊天数据与凭据均留在仓库外。
