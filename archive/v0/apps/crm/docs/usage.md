# 记录人物和交互

先创建人物，再将一次交互关联到一个或多个人。正文支持 Markdown，更新时只传需要改动的字段。

## HTTP

使用既有 API Bearer 令牌。viewer 令牌只读，不能新增、编辑或删除。

```http
POST /api/v1/crm/people
{"name":"张三","relationship":"朋友","tags":["同学"],"notes":"一起参加过读书会"}
```

```http
POST /api/v1/crm/interactions
{"person_ids":["张三ID","李四ID"],"date":"2026-10-15","type":"meeting","channel":"in_person","content":"我、张三、李四一起吃饭。","source":"manual"}
```

```http
PATCH /api/v1/crm/interactions/交互ID
{"content":"补充：约定下个月再聚。"}
```

省略字段保持原值。可选文本传 null 清空；aliases、contacts、tags、attachment_ids 传 null 清空列表。name、person_ids、date、type、source、content 不能为 null。

精确时间必须带时区；不确定时间就只传 date，不填零点。started_at / ended_at 入库转 UTC，date 使用北京时间。

## 查询

- `GET /api/v1/crm/people?query=张&tag=同学`：查名称、别名、联系方式、备注和精确标签。
- `GET /api/v1/crm/people/{id}`：人物详情、来源身份与最近交互。
- `GET /api/v1/crm/interactions?person_id=...&start=2026-10-01&end=2026-10-15`：人物历史，日期范围两端包含，跨日交互按覆盖范围匹配。
- 交互还可按 type / channel / source / query 筛选；列表只给 500 字预览，完整正文从 `GET /interactions/{id}` 读取。
- 列表均返回 items / next_cursor。limit 默认 50、最大 100；续页保留原筛选条件。
- 同一多人交互只有一条数据，出现在每个相关人物的历史中。

创建/修改/删除人物与交互分别使用 POST / PATCH / DELETE。`POST /people/{目标ID}/merge` 提交 `{"source_person_id":"来源ID"}`；目标资料优先、空字段补齐，交互和来源身份转入目标。

`PUT /people/{id}/identities` 提交 `{"source":"wechat","account":"我的账号命名空间","external_id":"对方会话ID"}`，用于绑定或纠正来源关联。不会按同名猜测合并。

## 附件

HTTP 使用 multipart 上传至 `POST /api/v1/crm/attachments`（字段名 file），返回附件 ID。交互通过 attachment_ids 关联，正文可写 `[方案.pdf](attachment://ID)`。

`GET /attachments/{id}` 读取元数据，available=false 表示文件尚未归档；`GET /attachments/{id}/content` 下载文件。返回数据不包含服务器本地路径。

## MCP

工具与 HTTP 共用相同业务：list_people / get_person / create_person / update_person / delete_person / merge_people / bind_person_identity，以及对应的交互工具和 upload_attachment / read_attachment。

```json
{"data":{"name":"张三","tags":["朋友"]}}
```

上例用于 create_person。update_person 和 update_interaction 使用 `changes` 参数；create_interaction 使用 `data` 参数。

get_interaction 默认每页 16000 字符，next_offset_chars 非空时续读；HTTP 详情返回完整正文。

upload_attachment 使用 Base64，每块不超过 256 KiB；第一块 final=false 返回附件 ID 和 next_offset。后续传 attachment_id / offset_bytes；最后一块 final=true。小文件可一次 final=true 完成。read_attachment 使用 offset_bytes / limit_bytes 续读。
