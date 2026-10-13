# 采集加工 M2 实施记录

本文件为历史实施记录。2026-10-12 用户将微信模型提炼移到后续分析模块，当前执行与新任务生成已关闭，历史提炼的预算、积压和失败不再属于采集验收。


日期：2026-10-11。M1 历史回填已完成，用户报告 M1 客户端开发完成。M2 服务端已验证并发布，历史会话回填与提炼按后台队列推进，客户端接入另行交付。开发、样本验证与构建先在隔离目录完成，再更新受影响服务。

## 实现范围

- 微信日会话 profile：按原 person_id、微信账号、原生会话及固定业务日期分组，保留方向、实际发言人、消息类型、原件及媒体状态；明确区分完整 reader 原文与未补齐的历史描述。
- 附加会员表保存尚未发布的消息归属，更新同步处理旧/新 scope；新增、迟到、跨日移动和删除均重算。联系人的名称作为输入依赖参与版本校验。
- 完整消息分块、按时间空档分段、全文搜索和原件分页；不跨独立消息拼接搜索，不以正文相同去重。
- 模型提炼使用独立队列和子进程，不占用原文加工与采集额度。模型默认不启用，运行配置按用户指示复用 CPA/grok-4.7；模型名、地址、凭据文件、阈值、超时、窗口和日请求预算均可配置。
- 模型资料与指令隔离，输出只接收结构化主题/要点并校验实际块引用。预算超出范围明确标注部分提炼；不生成长期状态、人格判断、记忆或 Bot 推送。
- 每个模型窗口预留调用预算并记录用量；成功窗口缓存用于中途失败后的重试。缓存写入检查当前输入、代数和租约，修改/删除同事务撤下缓存及派生产物。失败或中断的请求不能承诺未计费。
- 新增内部只读 insights 接口，结果绑定当前阅读输入；模型失败不影响原文阅读。沿用认证、原件身份、删除墓碑、既有卷和服务入口。

## 验证

`checks/conversation-processing-test.py` 使用合成材料；PostgreSQL 在随机 schema 及独立锁域中运行，测试结束清理。覆盖 M1 回归、会话隔离与排序、迟到/跨日移动、身份冲突、历史缺口、空消息/加密媒体、长消息与搜索、联系人依赖、模型引用/覆盖/预算、重试缓存和删除竞争。

PostgreSQL 33 项生命周期检查全部通过，另新增批量回填多成员场景通过；SQLite 33 项中 31 通过、2 项真实并发场景跳过；新的批量/覆盖索引回填三项在 SQLite 与 PostgreSQL 均通过。既有 unattended-collection 5 项通过。打包镜像内的合成消息阅读与新 insights 路由通过，错误 revision 为 409、无 viewer 凭据为 401，依赖检查通过。

真实源验证只读生产归档，复制到私有临时环境，不修改微信、CRM 或生产源记录；只对一个代表性长会话做真实模型调用，不将原文和模型输出写进仓库。

真实样本共 26,941 条 CRM 输入（含人物依赖），其中 26,842 条微信互动归成 798 个日会话，全部加工成功；531,342 字阅读内容、26,842 个消息块引用逐项核对原件与哈希。25,773 条为 reader 原文，1,069 条为未补齐的历史描述。CPA 实际模型名 grok-4.7 的一个窗口调用成功，返回 3 个主题、6 个要点且引用均有效；该长会话预算仅取一个窗口，结果正确标为 partial。引用验证不等于全面证明模型的理解准确。

## 运行配置

```json
{
  "conversation_model": {
    "enabled": true,
    "url": "http://192.168.31.201:8317/v1/chat/completions",
    "model": "grok-4.7",
    "api_key_file": "<现有私有凭据文件>",
    "api_key_field": "<需要从 dotenv 文件提取时填写>",
    "timeout_seconds": 120,
    "window_chars": 16000,
    "max_windows": 4,
    "max_output_tokens": 2000,
    "min_messages": 40,
    "min_chars": 6000,
    "daily_request_limit": 24
  }
}
```

阈值任一达到才提炼。日预算以 UTC 日累计，预留及失败请求也占额，最大 4 个窗口/会话；超长会话保持完整原文，提炼可以为 partial。模型请求不使用环境代理，不改变 CPA 或 Hermes 的模型设置及凭据。API 容器只需要非秘密配置，模型调用在宿主独立通道运行。

切换模型时同步宿主与 API 容器配置中的 model 字段，凭据字段仍仅在宿主配置；随后定向重建提炼任务。提示版本或阈值变化也需要重建。操作保留原文阅读版本，仅撤下提炼缓存并重新排队；每日预算可能使历史提炼分多日完成。停止模型使用 enabled=false，原文加工继续；停所有加工仍用 processing_enabled=false。

```bash
.venv/bin/hub rebuild-content --source crm --processor wechat-insights-v1 --force
.venv/bin/hub process-pending --lane reading --limit 50
.venv/bin/hub process-pending --lane model --limit 20
.venv/bin/hub processing-status
```

客户端接入另见 [M2 微信开发需求](client-requirements/m2-wechat-conversations.md)。本轮不修改 Mac 源码或采集 Agent。

## 发布及回退

2026-10-11 23:05 起正式运行镜像为 `local/personal-data-hub:0.4.1-conversations-m2-20261011-v4`。正式 mcp Compose 仅修改 crm.image，宿主配置增加 conversation_model 并重启既有采集与 webhook 服务；没有增加容器、定时设施、外部 MCP 工具或 Bot 推送。容器用户、挂载、网络、环境值及其他容器 ID 核对保持；启动检查 missing=[]、active_unplanned=[]、stopped_planned=[]，47 个计划内容器。

附加 schema migration 3 创建消息归属、模型调用账本及窗口缓存，并为现有单记录任务补归属；原件字段未修改。另为回填并发补建 ix_hub_records_kind_id_source 查询索引；先按类型从覆盖索引选窄 ID，再读取当批正文，避免扫描其他类型的大原件。线上 ID 页实测 0.059 秒，计划为三路 Index Only Scan/Merge Append。发布前加工表 JSONL 快照为 25,717,919 字节，Compose、宿主/容器配置与受影响源码保存在私有 `/home/yuwk/.config/personal-data-hub/releases/conversations-m2-20261011/`。正文、模型输出、令牌和私有配置不进入仓库。

旧 M1 镜像不能直接接受 migration 3。已准备 `local/personal-data-hub:0.4.0-reading-m1-schema3-20261011`：保留旧 API 入口，使用兼容的新存储/加工钩子及表定义，确保新的消息归属与删除仍可维护；包导入验证通过。回退 API 会暂时缺少 insights 路由，应保留当前源记录、墓碑、水位、卷与宿主新加工代码；需要停模型时设置 enabled=false，而不是恢复旧数据库快照或覆盖 Hermes 凭据。

线上真实 viewer 已验证 processing/status、新会话列表和既有 sources 接口 200，匿名列表 401。历史回填完成及实际正文/提炼的线上探针结果在后续状态段登记；当前后台任务数量不代替客户端验收。

## 线上最终核对

历史消息归属回填已完成，798 个微信日会话均 ready。真实 viewer 读取一个 70 条消息的会话，分两页得到 23,290 字原文，所有块的字符区间和输入哈希与原件一致；依据接口的续页可用，错误阅读版本返回 409。真实 insights 接口返回 grok-4.7 的当前提炼，主题引用均定位到实际消息块，覆盖状态与输入范围一致。客户端可以开始 M2 接入；历史模型提炼继续按日预算推进，不宣称全部已完成。

核对发现一条新采集的 Hermes JSON 执行元数据（1,050 字节）没有 normalized.content/raw.content，当前 document profile 报 document_body_missing。原件和附件完整，已登记为 M3 状态/结构化内容适配项；不能当成丢失的微信正文，也不能据此声称全部来源加工已覆盖。模型调用中断或失败保留账本及退避，租约到期后可恢复。
