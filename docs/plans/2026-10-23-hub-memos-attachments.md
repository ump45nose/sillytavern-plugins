# hub-api：Memos 附件上传与列表筛选（委派 fn 侧）

Mac 端 Memos 页已改成「顶部输入框 + 按天时间线」，左栏有 全部 / 置顶 / 有附件 / 已归档 四个视图。下面的接口上线前：

- 输入框的 📎 按钮显示为不可用，提示「附件要等 hub 提供上传接口」；
- 置顶、有附件两个视图在客户端按已加载的条目过滤（只覆盖已翻到的页）；
- 已归档视图如果 hub 返回的条目没有 `state` 字段，就显示「hub 还不能列出已归档的 Memo」，不会把普通 Memo 当成归档的展示。

约定沿用 `2026-10-21-hub-v2-tasks.md`：snake_case JSON、Bearer 设备令牌、不记录 URL / 头 / 正文、写操作只转发一次不重试、只操作当前用户自己的 Memo、写操作后失效 `memos` 缓存、单测用假服务、不向生产写测试数据。实现前请先对照 Memos 0.30 的官方 API 核对附件（attachment，旧称 resource）的创建与关联方式，下文只约定 hub 对 Mac 暴露的形状。

## 1. 上传附件

- `POST /api/v1/memos/attachments`，`multipart/form-data`，字段 `file`（一次一个文件）。
  - 返回 201 `Attachment`：`{name, filename, type, size}`。`name` 是 Memos 的附件资源名（如 `attachments/abc123`），之后关联到 Memo 时原样传回。
  - 大小上限按 Memos 实例的上传限制；超过返回 413，`{"detail": "文件超过 N MB"}`，N 为实际上限。
  - `type` 以 Memos 识别的 MIME 为准；不做服务端格式转换、不压缩。
  - 上传后尚未关联任何 Memo。
- `DELETE /api/v1/memos/attachments/{name}` → 204。只允许删除当前用户自己的、尚未关联任何 Memo 的附件，否则 409。Mac 在发送前移除附件时调用。
- 未关联的附件：如果 Memos 不会自行清理，hub 不必定时清理，在 README 里写明即可。

## 2. 关联到 Memo

- `POST /api/v1/memos` 的 body 增加可选 `attachments: [name]`，创建时一并关联。
- `PATCH /api/v1/memos/{id}` 的 body 增加可选 `attachments: [name]`，表示替换为这组附件（传空数组即全部移除）；不传就不变。
- 只接受当前用户自己的附件名，否则 422。
- 返回的 `Memo.attachments` 与现在一致：`[{name, filename, type}]`，可加 `size`。

## 3. 读取附件（如尚未实现）

- `GET /api/v1/memos/{id}/attachments/{name}`：只读代理，只接受该 Memo 自己的附件，原样返回字节并带上 `Content-Type`。
- 路径里 `{id}`、`{name}` 用资源名的最后一段（`memos/abc` → `abc`，`attachments/xyz` → `xyz`）。Mac 已按这个形状实现，404 时退回显示文件名。
- 可选 `?thumbnail=1`：Memos 能提供缩略图时返回缩略图，否则返回原图。Mac 现在不传这个参数。

## 4. 列表筛选与归档

`GET /api/v1/memos` 增加三个可选参数，都用 Memos 官方 filter 实现，不在 hub 扫全文：

| 参数 | 含义 |
| --- | --- |
| `pinned=true` | 只要置顶的 |
| `has_attachments=true` | 只要带附件的 |
| `state=ARCHIVED` | 只要已归档的；缺省为 `NORMAL`，行为与现在一致 |

- `Memo` 增加 `state`：`"NORMAL"` 或 `"ARCHIVED"`。Mac 靠这个字段判断 hub 是否支持归档视图，所以列表、单条、PATCH 的返回都要带上。
- `PATCH /api/v1/memos/{id}` 的 body 增加可选 `state`，只接受 `"NORMAL"`，用于从归档恢复；传 `"ARCHIVED"` 返回 422（归档仍走 `DELETE`）。
- 与 `tag`、`q` 可以同时使用。

## 5. 交付与验证

- 单测覆盖：上传成功 / 超限 / 非本人附件、创建与 PATCH 关联、删除已关联附件返回 409、三个筛选参数、`state` 恢复。
- 冒烟只做只读检查（列表带 `state`、筛选参数被接受），不在生产上传或改动 Memo；真实上传由用户在 App 里验证。
- 部署后告诉 Mac 侧，Mac 再启用 📎 按钮并接上拖入、粘贴截图、选择文件。
