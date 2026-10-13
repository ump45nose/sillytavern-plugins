---
name: orchestration
description: "编排纪律。任何非简单任务动手前必读。判定 inline vs 派活；用 kanban_create 把职责域任务交给独立 worker，并按 subscribed、终态事件、kanban_show、全任务收敛的闭环取回真实交付后合成。delegate_task 不跨 profile，不能当作 worker 派单。"
version: 2.1.0
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

**只要子任务落在任何 worker 的职责域内，就 `kanban_create(assignee=<profile>)`。** dispatcher 会 spawn 对应 worker，用**它自己的模型、权限、域内技能和记忆**干活。创建后必须保存 task id，并检查返回的 `subscribed`：true 表示当前原会话已登记终态续接，false 表示没有可靠的异步回流通道。

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

`subscribed=true` 时不空转轮询；gateway 收到终态事件后会唤醒创建任务的原会话。被唤醒后必须 `kanban_show(task_id)` 读取 run summary、metadata、comments 和 artifacts，再做归纳。`subscribed=false` 时不得说“会自动回流”，应明确说明并在后续轮次回查。

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

## 第四步：终态采集、汇总与上报（硬规则）

heartbeat 只表示 worker 存活并防止 stale reclaim，不是结果采集。收到 `completed/blocked/gave_up/crashed/timed_out` 后：

1. 对终态 task id 调 `kanban_show`；
2. 并行任务逐一核对，未全部终态则只报告进度；
3. 全部终态后，以看板保存的交付为唯一依据合成；
4. 给用户状态行，例如：`[ops] <标题> → 完成/阻塞 | 交付：<worker 结论>`。

**必须上报 blocker 和失败。** worker 任务被 block、或结果里有 blocker、或没交付物，就**不许**折叠成「已完成 / done」——用户把「缺失败说明」当成管道坏了（2026-07-19 实测反馈）。部分完成就透传部分结果 + 明确缺口。

## 设计注记
- kanban 是异步的：订阅成功后由所属 gateway 独占消费终态事件，并按创建时保存的 canonical session 唤醒原会话；到齐后才合成。
- cron / 无人在场会话不做强制派活；按各自 job 逻辑执行。
