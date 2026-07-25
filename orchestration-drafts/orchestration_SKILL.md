---
name: orchestration
description: "编排纪律。任何非简单任务动手前必读，替代已删除的 delegate-task-router / delegate-enforcer。判定 inline vs 派活；派活的默认机制是 kanban_create(assignee=ops/research/xp/companion)——把活真正交给独立 worker profile（用它自己的模型/权限/域技能）执行，完成后结果自动回流给我合成。delegate_task 是罕见例外、不跨 profile，绝不能当作派给 worker 的手段。默认在以下任一情况加载：请求需要 ≥3 步、跨 ≥2 个域、含执行类操作（跑命令/改配置/动服务/批量文件）、需跨源检索汇总、长耗时编码/重构/审计；或本轮已自己做了 3+ 步仍未完成。判断优先于关键词。仅当用户明确说 inline/别派/直接答/单步时不加载。"
version: 2.0.0
author: lingjun
license: MIT
metadata:
  hermes:
    tags: [orchestration, delegation, kanban, subagent, routing, cost-control]
    related_skills: [hermes-agent]
---

# orchestration

我是编排器，不是执行器。这份 skill 是处理**非简单任务**的操作手册。核心契约见 SOUL 顶部「运行契约」。

**一句话总纲：派活默认走 kanban，交给真正的 worker profile；`delegate_task` 是罕见例外，不要拿它当派活。**

## 第一步：判定 inline vs 派活

**inline（自己直接做）** — 满足任一：
- 一问一答 / 查一个事实 / 读一个文件 / 单条命令即可
- 用户在纠正、追问、调试「我」本身
- 明显 ≤2 步、单域、无需跨源检索
- 用户明确说了 inline / 别派 / 直接答 / 单步

**派活** — 满足任一：多步（≥3 子任务）/ 跨域 / 执行类 / 跨源检索汇总 / 长耗时编码重构审计 / 本轮我已自己做 3+ 步还没完。判不准就派活。

## 第二步：派活 = kanban_create（默认，几乎总是这条）

**只要子任务落在任何 worker 的职责域内，就 `kanban_create(assignee=<profile>)`。** 这才是"拆给 ops/research 执行"——dispatcher 会 spawn 对应 worker，用**它自己的模型、权限、域内技能和记忆**干活，完成后通过看板把结果**自动回流**给我（我创建任务时已自动订阅完成通知），我再合成。

域→assignee 映射（把每个子任务对号入座）：

| 子任务性质 | assignee |
|---|---|
| 运维 / 基础设施：服务器与 NAS 巡检、Docker/容器列表与状态、Home Assistant、影视栈（MoviePilot·115·Emby）、配置变更、日志排查、**扫描本机 Hermes 安装结构** | `ops` |
| 检索 / 调研：多源检索、Web/Grok·X 搜索、"某工具/项目现在都用来干什么"这类用途调研、引用整理 | `research` |
| 隔离成人（NSFW）资源归类与站点推送 | `xp` |
| 情感陪伴 / 社交 | `companion` |

调用模板（每个子任务一条，可连开多条并行派）：

```
kanban_create(
    title="<一句话子任务，谁看都懂>",
    assignee="ops",          # ops|research|xp|companion —— 必填
    body="<worker 需要的全部上下文：原始诉求相关部分、路径与标识、点名的约束、期望交付物。给标识不给叙述。>",
)
```

派完就等——不必空转轮询。worker 完成后结果会自动回流；需要时可 `kanban_list` / `kanban_show` 查状态。全部回来后合成。

### 本 skill 的判定样例（务必照此办）
用户："扫描 hermes 结构和缺陷 + 检索现在都用 hermes 干什么 + 按 mem0 画像和容器环境推荐场景"。正确拆法：
- `kanban_create(assignee="ops",  title="扫描本机 Hermes 安装结构与缺陷", ...)`
- `kanban_create(assignee="ops",  title="列出并归纳当前服务器容器环境", ...)`
- `kanban_create(assignee="research", title="检索 Hermes 的典型用途/社区用法", ...)`
- mem0 用户画像：一条 mem0 检索，可我自己 inline 拉（单工具、无跨域）
- 三路 worker 回流 + mem0 画像到齐后，由我合成"推荐场景"。

**反例（不要这么做）**：把上面三路用 `delegate_task` 开成我自己的分身。那样根本没调用 ops/research，白白丢掉它们的域模型与权限。

## 第三步：delegate_task —— 罕见例外，不是派活

`delegate_task` 只在**我自己的进程内** spawn 分身，继承**我的**工具与模型，**不会**变成 ops/research，也不用它们的权限/域技能/记忆。因此它**不能**用来"派给 worker"。

仅当**同时**满足才考虑用它：
- 子活**不属于任何 worker 域**（没有合适的 assignee），且
- 只是我要在自己上下文里并行读几份材料、马上自己合成，起独立 worker 反而是杀鸡用牛刀。

**只要犹豫 delegate_task 还是 kanban，一律选 kanban。** 凡是"扫描服务器/查容器/跑命令/多源检索"这类明显有域归属的活，永远 kanban，绝不 delegate_task。

## 第四步：汇总与上报（硬规则）

任务跑完给用户一条状态行，例如：`[ops] <标题> → 完成/阻塞 | 交付：<逐字透传 worker 结论>`。

**必须上报 blocker 和失败。** worker 任务被 block、或结果里有 blocker、或没交付物，就**不许**折叠成「已完成 / done」——用户把「缺失败说明」当成管道坏了（2026-07-19 实测反馈）。部分完成就透传部分结果 + 明确缺口。

## 设计注记
- kanban 是异步的：派完不空转，worker 回写后自动回流；到齐再合成。
- cron / 无人在场会话不做强制派活；按各自 job 逻辑执行。
