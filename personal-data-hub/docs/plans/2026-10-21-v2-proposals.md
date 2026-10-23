# v2 大改方案（待审阅）

配套设计稿：`docs/design/v2/index.html`（浏览器直接打开，六个分区对应下面六节）。

审阅后按你的选择再动手；每节末尾的「需要你定」是开工前要确认的点。数据缺口统一列在最后，方便你在 fn 上委派。

---

## 1. Plaud 录音模块（#5）

**目标**：录音不再只是交流记录里的附件，而是独立模块，主体是转录稿 Markdown，音频作为附件播放。

**设计**

- 简略卡：最近一条录音的标题、时间、时长，两行摘要；底部「今天 N 段 · 共 1:46」。
- 详细卡 / 独立页：左侧最近录音列表（标题、时间、时长、涉及的人），右侧渲染转录稿 Markdown（标题、说话人、列表、引用），顶部是音频附件条（播放 / 暂停、拖动进度、1× / 1.5× / 2×）。
- 交流模块里的录音条保留，点「转录稿」跳到 Plaud 模块对应条目，不再弹小窗。

**数据**：hub 现在只有按 id 取音频（`/recordings/{id}/audio`）和转录（`/recordings/{id}/transcript`），没有「最近录音列表」。需要 fn 新增：

```
GET /api/v1/recordings?source=plaud&limit=20
→ items: [{ id, title, started_at, duration_seconds, summary, people: [name], has_transcript }]
```

**工作量**：Mac 约 1 天（含一个块级 Markdown 渲染器）；fn 一个只读接口。

**需要你定**：转录稿里是否按说话人分段着色；列表默认显示多少天。

## 2. Token 重新设计（#8，逻辑对齐 Token Monitor）

**设计**

- 上半区固定看「全部时间」，右上角切换「热力图 / 趋势」：
  - 热力图：GitHub 式按天格子，从第一条记录（Token Monitor 本机从 9/16 起）到今天，悬停显示当天总量、成本、主力模型。
  - 趋势：按天面积图 + 7 日均线，可悬停。
- 下半区「日 / 周 / 月」切换，五块并排或两列：
  - 额度：沿用现在的实时额度窗口。
  - 工具：Codex / Cursor / pi / Claude Code / Antigravity … 占比条。
  - 模型：按模型的用量与成本，Top 8 + 其他。
  - 设备：MacBook Pro / Air … 占比条。
  - 会话：用量最高的会话，显示会话标题、工具、模型、用量。
- 主页简略卡保持现在的样子（今日总量 + 两个最紧的额度）。

**数据**：hub 现在给的是 tools、devices（只有当日分布）、buckets、limits。缺：全时间按天序列、按模型、按会话、非当日的工具 / 设备分布。Token Monitor 本机已有这些（`daily-history-archive.json` 按天 × 工具 × 模型；会话标题经它自己的 hub 同步），需要 fn 在 token 模块补：

```
daily: [{ date, total, cost, top_model }]        # 全部时间，不随 range 变
models / tools / devices: [{ id, name, total, cost }]   # 跟随 range
sessions: [{ id, title, tool, model, total, cost, started_at }]  # 跟随 range，Top 10
```

**工作量**：Mac 约 1 天；fn 扩展 token 模块。

**需要你定**：会话标题是否允许显示（Token Monitor 有「同步会话标题」开关）；成本显示美元还是人民币。

## 3. Memos 原生页（#12）

**难度评估**：中等，建议做，分两步。

- 第一步（约 1 天）：原生只读时间线 + 发布。左栏：发布框、标签列表、按月的活跃热力格；主区：Memo 卡片流（正文 Markdown、标签 chip、时间、可见性、图片缩略图），标签筛选和搜索。编辑 / 删除先给「在 Memos 中打开」。
- 第二步：编辑、删除、置顶，在卡片上直接操作。

**数据**：hub 现在只给最近 20 条和标签。需要 fn 扩展：`GET /api/v1/memos?cursor=&tag=&q=`（分页、筛选、搜索）；第二步再加 `PATCH` / `DELETE /api/v1/memos/{name}`。也可以绕过 hub 直连 Memos API，但那样外网用不了、还要再管一个令牌，不推荐。

**需要你定**：第一步是否够用；内嵌网页是否保留为「网页版」入口。

## 4. 复盘独立页面与模块尺寸（#13 后半、#15）

**复盘页**：把复盘从单独窗口搬进主窗口，作为内置页面「复盘」（侧栏 ⌘6），结构与「电脑历史」页一致：左侧阶段 / 日报 / 周报列表，右侧编辑区。⌘⇧R 改为直接跳到这一页；单独窗口保留为右键「在新窗口打开」。页面类型新增 `review`，安卓读到未知页面类型应跳过而不是报错（需告知安卓侧）。

**模块尺寸**：宽度已经可调（编辑布局时详细卡片 4–12 列，这次已上线）。高度建议做三档而不是自由拖拽：

- 自动：按内容（现状）。
- 中：固定约 360pt，超出在卡片内滚动。
- 高：固定约 560pt，超出在卡片内滚动。

自由拖拽改高度要做拖动手柄、行对齐和与其他卡片的避让，复杂度高、收益有限，不建议。

**需要你定**：复盘单独窗口是否还需要；高度三档是否够用。

## 5. 本地 agent 接入（#14）

**建议：一个本机 MCP 服务做统一入口，agent 各自接入。** Codex、pi、Claude Code、Antigravity 都支持 stdio MCP，所以只写一个服务，四家通用，不需要分别适配。

- 服务：签名后的 App 自带，`Personal Hub.app/Contents/MacOS/PersonalHub --mcp`。用 App 自己的二进制跑，能读到钥匙串里的 hub 设备令牌和 Google 凭据，不需要再发一份令牌给 agent。
- 工具分两类：
  - 读：今天概览、任务与日程、健康、账单、交流、Token、电脑历史、复盘会话与材料、阶段目标。
  - 写：新增 / 完成 / 改期任务，新建日程，Memo 草稿，日报 / 周报草稿，阶段目标评论草稿。
- 写入安全：写工具只生成「待确认变更」，App 菜单栏出现提示，点开逐条确认后才真正写入；复盘终稿、阶段结案永远不开放给 agent。每次调用记本机审计日志。
- App 内入口：⌘K 搜索框加「问 AI」，调用本机 agent 的非交互模式（第一版 `codex exec`，之后加 `claude -p`、pi、Antigravity），自动挂上这个 MCP 服务，结果流式显示，写入同样走待确认。
- 设置页「连接 agent」：检测本机装了哪些 agent，给出各自的配置片段（Codex 的 `config.toml`、Claude Code 的 `claude mcp add` 等），可一键复制；写入别家配置文件前先备份并让你确认。

**不建议**：反过来依赖各收集端自己的 MCP 拼统一入口——数据分散、权限各管各、写入无法统一确认。

**工作量**：MCP 服务 + 待确认队列约 2 天；App 内「问 AI」约 1 天；每多一个 agent 约半天。

**需要你定**：第一版写工具的范围（建议只开任务和草稿）；「问 AI」默认用哪个 agent。

## 6. 日报生成（#15 后半）

现状：personal-review 每晚冻结当天材料、生成日报会话，灵珺（hermes）在 Telegram 推送；你在 Telegram 或 App 里确认。App 缺的是「帮我起草」。

**方案**

- A. 本机起草（推荐先做）：日报编辑区加「AI 起草」。App 把当天材料、模板、字段规则（字数、情绪词、未解最多两项）交给本机 agent（走第 5 节的通道），返回各字段的建议，填进表单作为草稿并标出「AI 建议」；你改完照常「预览并确认」。不改 NAS。
- B. 请灵珺起草：hub 新增 `POST /api/v1/review/sessions/{id}/draft`，由 personal-review 让 hermes 起草并存为建议草稿；App 和 Telegram 都能看到。手机端、Mac 不在线时也可用，但要改 NAS 上的 personal-review。
- 两者可以并存：编辑区「AI 起草」菜单里选「本机」或「灵珺」。

确认、写 Memos、Telegram 已归档通知的链路不变；起草只产生草稿，不会自动确认。

**需要你定**：先做 A 还是 A+B；起草是否需要读到当天电脑历史和交流原文（隐私范围）。

---

## 数据缺口（可直接委派 fn）

| 用途 | 现状 | 需要 |
| --- | --- | --- |
| 网络：已用 / 套餐总量（#6） | `net` 只有 `month_bytes`、`today`、`hourly`，`pools` 为空 | `pools: [{ id, name, used_bytes, total_bytes, expires_on }]`，每个流量包一项 |
| Plaud 模块（#5） | 只有按 id 取音频和转录 | `GET /api/v1/recordings?source=plaud&limit=` 列表接口 |
| Token 重设计（#8） | tools / devices 仅当日，无模型、会话、全时间序列 | token 模块补 `daily`（全部时间）、`models`、`sessions`，tools / devices 跟随 range |
| Memos 原生页（#12） | 最近 20 条 + 标签 | `GET /api/v1/memos` 分页 / 标签 / 搜索；第二步 `PATCH` / `DELETE` |
| 日报灵珺起草（#15 方案 B） | 无 | `POST /api/v1/review/sessions/{id}/draft` |

## 本机发现，非本项目代码

- skysight-sync 自 10/20 起每天同步失败：`~/.codex/memories/extensions/skysight/resources/2026-10-19T13-30-00-gsYb-10min-memory-summary.md` 的 frontmatter 里 `description` 含未加引号的冒号，YAML 解析报错后整次同步中止，所以 MacPro 的电脑历史停在 10/19。App 这次已改为同时读取本机实时摘要（今天的 MacAir 数据已能显示），但跨设备的数据仍要靠修好同步：给该文件的 description 加引号，或让 skysight-sync 遇到坏文件跳过而不是中止。
