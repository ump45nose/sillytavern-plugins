# M2 客户端开发需求：微信会话阅读与提炼

2026-10-12 范围调整：微信模型提炼已暂停，后续分析模块统一设计。当前只需要会话归组、原文、时间分段、媒体和检索；下文提炼接口为历史说明，当前返回 state=disabled，不要求 Mac 接入这项功能。


日期：2026-10-11。本对话只实现服务端，用户在 Mac 开发。M1 文档阅读按用户反馈已完成；本节点新增 conversation 类型和独立提炼接口，沿用 M1 的服务地址、viewer 凭据、分页及状态规则。

## 阅读入口

`GET /api/v1/contents?source=crm&variant=wechat_day` 返回日会话列表；搜索可同时传 query，范围为完整消息正文，不拼接不同消息制造命中。正文仍用详情的 content 路由，必传 revision，按 next_after 续页。列表公共 schema_version 仍为 1，新增 `type=conversation / variant=wechat_day`。

会话按业务时区 Asia/Taipei 的日期、原 person_id、微信账号命名空间及原生会话 ID 分组。同名不合并，群聊不当作某个人的发言；缺失时间进入“时间未知”，不能用整理时间充当发生时间。scope_key 不由客户端解析。

详情 metadata 增加 person_id、account_namespace、conversation_id、business_date、name、message_count、input_message_records、duplicate_records、body_chars、directions、fidelity_counts、segment_count、started_at/ended_at、segmentation、assets。这些计数只针对已归档记录，不代表微信全历史采集覆盖。

## 消息控件

- blocks 的 `type=message`，text 为原消息纯文本；保留空格、换行和空消息。不作为 Markdown/HTML 执行，不将来源 JSON 堆成阅读正文。
- metadata 提供 message_key、message_index、occurred_at、direction、sender、sender_id、message_type、conversation_type、fidelity、body_chars、empty、assets、media_state。
- direction 支持 inbound/outbound/unknown。群聊使用实际 sender/sender_id；缺失时显示“发言人未知”，不要取会话名或 person_id 当发言人。
- 长消息有 part/part_count/continuation；只拼接同一 message_index 的连续分块，不在块间新增换行，也不将两个独立消息拼成一条。
- 每个块 key 可用来定位主题引用；ordinal 用于正文分页。搜索 match.ordinal 指向正文块；跨长消息分块的命中可能包括上一块尾部，定位时一并载入前文。
- refs 提供源记录、输入 hash、字段路径及字符区间；同一来源消息身份的重复归档可以提供多个 refs。正文相同而身份不同的消息仍是两条，身份冲突也会保留并告警。
- fidelity=original 表示已有 reader 正文；legacy_description 表示原始正文未补齐，仅有历史描述；missing 表示没有正文。后两者需明确标注，不当作聊天原话。
- media_state 支持 none、not_archived、encrypted、archived_original。图片加密字节与原 SILK 不等于可预览图片/可播放音频；下载沿用 assets 接口和哈希核对。不显示虚假的解码成功。

按 segment_id 折叠连续交流段，segment_start 表示段首。初版以 30 分钟空档分段，segmentation.method=time_gap；此分段不等于模型识别的语义主题。可用真实时间和首条消息摘录做段标题，注明是时间分段。

## 主题与要点

新增 `GET /api/v1/contents/{conversation_id}/insights?revision=<阅读版本>`，沿用 viewer 鉴权。这里的 conversation_id 指 contents 返回的 id，不是微信原生 ID。401、404、409 按 M1 处理；切换会话或 revision 时清掉旧提炼，不混读两个版本。

返回 id/revision/state/result/error_code。state 为 pending/running/failed/ready/stale/not_needed/model_changed；只有 ready 且 result 非 null 才显示当前提炼。not_needed 表示短会话不需要模型提炼；没有提炼不妨碍原文阅读。失败显示可重试的服务状态，不把错误原因或模型配置塞进聊天正文。

result 包含 model、prompt_version、themes、key_points、summary、selected_blocks、total_blocks、complete、scope、windows、requests、cached_windows、warnings。

- themes：title、description、block_keys；key_points：text、block_keys。每项均有实际消息块引用，点击可在正文中定位，并可进一步展开对应 refs 原件。
- 服务端限制模型输入。complete=false / scope=partial_conversation 时，显著显示“部分会话提炼”及覆盖块数；不能写“完整总结”。summary 为主题描述组合，不是对整个用户状态的分析。
- 显示模型生成标识，保留 model_generated_review_required 提示；有效引用证明引用存在，不能证明每句模型理解绝对正确。
- 更新原件后旧提炼不会作为当前结果返回；删除会同步撤下包含已删除消息的提炼。当前模型设置变化时 model_changed 表示待重建，不显示旧模型结果冒充新结果。

原件依据接口现在支持 revision、after、limit（1–100），返回 inputs/next_after。会话依据可能多页，必须续取；after 是上一页返回的原记录 ID，不能当数字 offset。M1 单记录默认调用保持兼容。

## Mac 验收

1. 同名联系人、不同微信账号和群聊隔离；实际 sender 与方向正确，未知时间/发言人明确标注。
2. 长消息续页后原文完整，跨块搜索可定位；相同文本的不同消息不会被合并。
3. 时间分段可折叠，主题与要点可展开到实际消息依据；部分提炼的范围清楚。
4. 模型排队/失败时原文正常阅读；编辑、跨日修改和删除后刷新不保留旧消息或旧提炼。
5. 历史描述、未下载媒体和加密媒体不显示为完整原文/可播放媒体。

合成响应见 [M2 API 样例](m2-api-fixtures.json)。样式整理、快捷记录和长期分析不在本节点。
