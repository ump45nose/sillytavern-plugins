> 历史设计／验收记录。2026-10-15 起来源范围已收窄，本文中的已移除来源和开发要求不再执行。当前范围见 [来源清理计划](../plans/2026-10-15-source-cleanup.md)。

# M1 客户端开发需求：Memos 与日报阅读

日期：2026-10-11。服务端负责加工、数据契约、接口、生命周期和部署；Mac 代码、编译、安装和交互验收由用户在 Mac 完成。本需求用于独立开发，不要求先完成样式重构。

服务端已发布到原入口 `https://crm-home.172906573.xyz`，镜像为 `local/personal-data-hub:0.4.0-reading-m1-20261011-v2`。新接口已使用真实 viewer 凭据验证正文、分页、原件依据和附件；历史对象按后台队列逐步就绪。客户端开发可以开始，尚未整理的对象按下文状态规则展示。

服务端本节点验收通过即可继续 M2；客户端联调结果用于整体采集侧验收，不再阻塞服务端下一节点。服务端新增阅读类型或遇到客户端依赖时，在本目录追加对应需求。

## 用户应能完成的操作

1. 浏览 Memos 笔记与日报的可读标题、短摘录、来源、日期、整理状态。日报正文与 Hermes 执行记录分开；无发生时间不显示伪造日期。
2. 打开并阅读完整 Markdown 正文，支持标题、段落、列表、引用、链接；超长正文有明确续页，不把短预览当全文。空正文有明确提示。
3. 搜索完整正文，列表显示正文命中片段；打开后能加载到命中分块，定位或高亮实际正文。命中片段不能替代正文。
4. 查看标签、归档附件、来源记录和原件版本；保存附件沿用已有认证下载与 SHA-256 校验。
5. 编辑、删除、整理失败和未知格式得到明确反馈。正文分页期间内容改变时清掉旧页面并重新加载；删除后清掉正文、摘要和附件入口。

## 接口与鉴权

继续使用现有 HTTPS 服务地址和 Keychain 中的 viewer token：`Authorization: Bearer <viewer token>`。不要引入新账号、写入 token 或 MCP 连接。

| 请求 | 参数与结果 |
| --- | --- |
| `GET /api/v1/contents` | `source`、`variant`、`query`、`start/end`、`limit`（1–50）、`cursor`；返回 `items/next_cursor` |
| `GET /api/v1/contents/{id}` | 公共头加 `metadata/assets`；不存在返回 404 |
| `GET /api/v1/contents/{id}/blocks` | 必传 `revision`，首屏 `after=-1`；之后使用 `next_after`，`limit` 1–50；返回 `blocks/next_after` |
| `GET /api/v1/contents/{id}/evidence` | 返回该阅读版本的输入 `record_id/input_hash/current_hash/current_matches/record` |
| `GET /api/v1/processing/status` | 加工任务、阅读对象、失败及来源覆盖；与原采集状态分别展示 |
| 原有原件/附件接口 | `/api/v1/records/{record_id}`、`/api/v1/assets/{asset_id}` 保持 |

`start/end` 必须带时区，范围为左闭右开；默认不限定时间。`cursor` 必须原样传递，不拼 offset；筛选或查询改变后清空 cursor 并从第一页重新加载。`next_cursor=null` 表示本次没有续页。列表是实时 keyset，不是冻结快照；刷新后可能出现迟到内容，追加页按 content id 去重。

M1 的 `type=document`，`schema_version=1`。变体为 `note`、`daily_review`、`execution_log`；默认主列表排除执行记录，指定 `variant=execution_log` 或其来源可读取执行记录。普通 Memos 过滤 `source=memos`；日报过滤 `variant=daily_review`。不要再在客户端从 500 字预览中识别 `#日报` 或从 raw JSON 猜正文。

### 公共头

- `id` 是 **content id**，不等于原始 record id；只用于 contents 路由。`scope_key` 是服务端分组键，客户端不要解析。
- `source/account/type/variant/schema_version/revision` 为必需字段；未知类型或 schema 显示“当前客户端暂不支持”，不能偷偷退化为 JSON 字段堆叠。
- `occurred_at` 为源端发生时间，可以为空；`business_date` 为文档明确日期，可以为空。`timezone` 保留来源时区。客户端自行格式化时间，不改服务端分组。
- `title/preview/summary`：preview 是短摘录，summary 可以为 null，明确有摘要才显示摘要区。不能将 preview 标为 AI 摘要或补出 summary。
- `processing.state` 支持 `pending/running/ready/stale/failed`；`published_at` 是整理发布时间，不是内容发生时间。仅 `revision>0 && state=ready` 进入正常阅读。
- `warnings` 为质量提示，`coverage` 为覆盖声明。NUL 在阅读副本替换时有 `nul_replaced_in_reading_copy`，归档原件不变。
- `match` 仅正文搜索命中时可出现：`ordinal/excerpt`。使用 ordinal 加载到该块；excerpt 是命中摘录。
- `content/evidence` 是已认证的相对路由。详情里的 `metadata` 提供 `record_id/format/body_chars/empty/origin/record_kind/business_date/state/pinned/tags/relations/source_ref` 等字段；不要要求列表也有这些字段。
- `assets` 仅在详情提供，保持现有 `id/name/media_type/size` 契约。relations 是来源关系，不假造可点击的 content id；初版可通过原件核对。

### 正文分块

`blocks` 中每项为 `key/ordinal/type/text/refs/metadata`。M1 的 type 为 markdown；`text` 按 ordinal 拼接后就是完整正文，保留空白、换行和 Markdown。传输分块可能截在段落或 Markdown 中间，不能把每个块误认为独立文章或强行插入换行；渲染时应先拼接已有块或保留解析连续性。

每页最多 256 KiB，可能因字节预算少于 limit，因此只依赖 `next_after` 判断是否继续。`refs` 包含原件 ID、hash、正文路径与 char_start/char_end（Unicode 字符偏移）；不把偏移当 UTF-8 字节或 Swift UTF-16 下标。

分页请求固定使用打开详情时的 revision，不能把新版本块混入旧版本。搜索深层命中时可逐页加载到 match.ordinal，保留加载状态和取消能力，不限制成“前 50 块就是全文”。

### 状态与错误

| 情况 | 客户端行为 |
| --- | --- |
| pending/running | 显示等待整理/整理中，可刷新；不显示空白“完整正文” |
| stale | 显示原件已更新，等待整理；不继续使用旧正文分页或把旧内容当当前搜索结果 |
| failed | 显示整理失败，保留来源/原件入口；错误原因可从 processing/status 查看 |
| 409 `content_changed` | 清理旧块、旧摘要和旧依据，重新取详情和第一页；防止两个 revision 混读 |
| 404 `content_removed` | 清理正文、摘要、附件和依据，关闭或显示删除提示，同时刷新列表 |
| 网络错误 | 可重试，不误报删除；如果保留当前屏幕，明确未完成最新状态核对，不能承诺离线立即感知删除 |
| 401/503 | 沿用已有连接凭据与服务提示，不尝试使用写入凭据补权限 |

打开详情时定期核对当前头（建议每 30 秒）或在重新激活/用户刷新时核对；列表刷新与详情核对分开。快速切换对象或查询时，取消旧请求/使用请求代数，防止旧响应覆盖新页面。初版不新增永久正文缓存。

## Mac 验收清单

- 普通笔记、日报、执行记录分别进入正确入口；日报识别来自 variant/business_date。
- 长文分页后，拼回内容与原件 normalized.content 或 raw.content 相同，除了明确提示的 NUL 替换；末尾可到达。
- 中文搜索命中 500 字预览以外和分块边界上的内容；打开能定位，附件/原件依据可读取。
- 快速切换对象、搜索、来源，旧请求不会覆盖当前内容。
- 打开期间编辑/删除原件，当前页面刷新后不保留旧正文；续页收到 409/404 时正确清理。
- unknown schema、空正文、待整理和失败不显示为“阅读完成”。
- 保留现有 Keychain、登录项、微信和电脑活动采集任务、身份、水位及授权；本需求不要求重新安装采集组件或变更其权限。

合成请求/响应样例见 [M1 API fixtures](m1-api-fixtures.json)。它们可直接作为 Mac 解码和阅读状态测试输入，均不含私有真实正文或凭据。
