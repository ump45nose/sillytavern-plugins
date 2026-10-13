# Grok Bot 的 CPA 接入与 Tailnet 恢复

源码归 `app-configs/grokbot`，NAS 正式部署沿用 `ai` 组的 `cli-proxy-api`，没有新增容器。

## 产物与使用顺序

| 文件 | 用途 |
| --- | --- |
| [PROMPTS.md](PROMPTS.md) | 发给 Grok Bot 的安装、SSH 和手动恢复提示词，以及每日例程的配置入口。 |
| [proxy.js](proxy.js) | 将 Grok Agent 文本对话适配为 OpenAI 格式接口；Bot 部署路径为 `/home/box/cursor-proxy/proxy.js`。 |
| [recover.py](recover.py) | 保存已有 Tailnet 身份、安装开机入口，并守护 Tailscale 和适配器；Bot 部署路径为 `/home/box/cli-config/grokbot/recover.py`。 |
| [daily-recovery.json](daily-recovery.json) | 每日恢复任务的名称、提示词和计划规格，需通过 Grok 平台原生例程工具登记。 |
| [daily-recovery-grokbot-2.json](daily-recovery-grokbot-2.json) | 新 Bot 的独立每日恢复任务规格，保留旧 Bot 的任务。 |
| [.gitignore](.gitignore) | 排除私有配置、身份文件、SSH 主机密钥、二进制和日志。 |

首次连接按提示词完成安装、用户浏览器授权和 Tailscale SSH，然后配置 CPA 文本适配器。已有部署的恢复使用 `recover.py ensure`，不需要重复首次登录流程。

`recover.py` 面向当前 Grok Computer 的 Linux 环境，依赖 Python 3、Node.js、原有 sudo 权限和已有适配器私有配置。它会保留已安装的 Tailscale 二进制及身份；仓库不携带这些私有运行文件。新 Computer 的首次配置需要先完成 Tailscale 授权与适配器部署。

## CPA 调用

- 本地地址：`http://192.168.31.201:8317/v1`
- 使用现有 CPA 客户端密钥。

| CPA 模型名 | Bot Tailscale IPv4 | Linux 用户 | CPA 渠道 | 独立桥接密钥文件（NAS 私有） |
| --- | --- | --- | --- | --- |
| `grokbot` | `100.103.12.86` | `box` | `grokbot-cursor` | `/vol2/1000/Docker/stacks/ai/env/grokbot-bridge.json` |
| `grokbot-2` | `100.71.234.37` | `box` | `grokbot-2` | `/vol2/1000/Docker/stacks/ai/env/grokbot-2-bridge.json` |

两个渠道分别访问对应 Bot 的 `http://<Tailscale-IP>:1341/v1`，显式使用 `proxy-url: direct`，并为该渠道设置 `request-retry: 0`。新 Bot 作为额外模型加入，旧 Bot 的渠道、密钥和部署保持不变。

当前 Grok Gateway 不提供模型列表和模型切换 API。旧版 `agentDefaultModel` 字段已移除，因此没有继续发布原渠道的 13 个 Claude/Grok 模型别名。`grokbot` 和 `grokbot-2` 各自指向对应 Bot 的默认模型；模型名称不代表可下载的模型权重。

`proxy.js` 将文本消息交给原有专用 `cursor-proxy-agent`，按 `clientNonce` 和 `requestId` 获取回复。该 Agent 保留对话上下文。这是 Agent 对话适配；工具调用、图片输入和结构化输出会被拒绝。SSE 在 Agent 产生回复后发送，不能提供底层模型的实时 token 流，也不能保证 Agent 不执行自身工具。token 用量为估算值。

适配器只监听 `127.0.0.1:1341`，由 Tailscale Serve 的 TCP 1341 转发。没有启用 Funnel。模型接口额外验证独立密钥；Gateway 原有监听配置未修改。适配器每次请求重新发现 `sand-data/gateway.json`，不会把 Gateway token 写入 Git 或请求日志。

NAS 渠道配置在 `/vol2/1000/Docker/CPA/config.yaml`。每个桥接密钥保存在上表对应的 NAS 私有文件和对应 Bot 的 `/home/box/cursor-proxy/config.json` 中；这些文件均为 0600，不进入本仓库。两个 Bot 的文件路径相同，但位于各自独立的 Computer 中，身份和专用 Agent 不共享。

## 恢复

Bot 上的持久文件：

- `/home/box/cli-config/grokbot/recover.py`：幂等恢复命令和后台守护。
- `/home/box/cli-config/grokbot/bin/`：保留的 Tailscale 二进制。
- `/home/box/cli-config/grokbot/tailscaled.state`：已有 Tailnet 身份及配置，0600。
- `/home/box/cli-config/grokbot/ssh-host-keys.tar`：SSH 主机密钥的私有备份，0600。
- `/home/box/cursor-proxy/`：适配器、专用 Agent ID 和私有配置。

这些路径属于当前平台开启的 box-store 同步范围。守护每 5 秒检查 Tailscale 和适配器进程，异常退出后重启，并保留原身份。Tailscale 继续使用 userspace networking 和 Tailscale SSH；没有安装 OpenSSH，也没有变更 DNS、Exit Node、系统代理或防火墙。

运行二进制部署在 `/usr/local/libexec/grokbot/`（root 所有），运行状态在 `/var/lib/tailscale/`，并显式指定 `--statedir=/var/lib/tailscale`。普通环境重启的入口已写入 `/usr/local/bin/start-sand-box`，在 box-store 恢复后启动守护。平台镜像重建可能覆盖该系统入口，`recover.py ensure` 会重新安装启动入口并部署服务。

在 Grok Bot 的 Computer 终端运行：

```bash
python3 /home/box/cli-config/grokbot/recover.py ensure
python3 /home/box/cli-config/grokbot/recover.py status
```

从能连接 Bot 的 Mac 运行：

```bash
ssh box@100.103.12.86 'python3 /home/box/cli-config/grokbot/recover.py ensure'

# 新 Bot
ssh box@100.71.234.37 'python3 /home/box/cli-config/grokbot/recover.py ensure'
```

若重建后 Tailscale 尚未启动，应在 Grok Bot 中执行恢复命令，SSH 此时无法提供初次恢复入口。

旧 Bot（`grokbot`）的主 Bot 上已用平台原生 `UpdateRoutine` 登记云端例程 `tailnet-cpa`，最终计划为每天 **06:30（Asia/Shanghai）**，规格见 `daily-recovery.json`。平台状态确认只有这一条同名例程且已启用。每日任务会唤起 Bot，可能计入模型额度；普通后台守护只消耗系统资源。任务要求正常且没有恢复动作时保持静默，恢复异常或需要用户操作时通知。

**云端自动执行尚未通过验收。** 平台记录一次 failed，单次真实调度测试也未观察到恢复命令执行，详见下方验证状态。因此镜像重建后目前应在 Grok Bot 中手动执行 `recover.py ensure`，不能保证等待每日例程就会自动恢复。

不要用 Gateway 的 `createAgentAutomation` 代替平台原生例程工具：当前 host 的 automation cloud sync 明确排除 session box 和 temporal harness，这类本地记录不会成为有效的云端任务。实际配置应通过原生 `UpdateRoutine` 维护，不能只改本地 `automation.json`。

恢复依赖平台仍能恢复这些持久文件、启动 Computer 终端和提供原有 sudo 权限。每日任务是模型驱动的恢复入口，不是平台提供的确定性开机钩子；删除持久数据或登录身份失效需要用户重新授权。未执行整台 Computer 的重启或销毁重建测试。

## 验证状态（2026-10-08）

CPA 模型列表、文本回复和 SSE 均已验证；适配器和 Tailscale 进程异常退出后，守护恢复了原有 Tailnet 身份、IP 和 CPA 调用。修订版再次受控重启 Tailscale 后，SSH 登录通过，身份、地址和 SSH 主机密钥保持不变；系统启动入口的实际调用和 NAS 容器启动检查也通过。

首版 Tailscale 进程重启后，SSH 在 banner exchange 阶段超时。后续诊断确认原因是缺少 SSH 所需的状态目录，日志报 `no var root for ssh keys`：仅指定自定义 `--state` 时，Tailscale 只会从名为 `tailscale` 的父目录推导状态目录（[上游实现](https://github.com/tailscale/tailscale/blob/main/cmd/tailscaled/tailscaled.go)）。修订版显式传入 `--statedir=/var/lib/tailscale`，并将 CLI 超时延长至 45 秒，避免高负载时过早失败。

Grok 自动安全审查曾要求用户确认 `sudo tailscale set --ssh`；用户已完成该授权和命令执行。修订版已部署。

原生 `UpdateRoutine` 的创建、更新事件及平台注入的例程状态确认云端例程存在。Gateway 的手动触发接口返回 HTTP 409、`automation-run-now/refused`；平台状态记录 22:37:37 failed，没有错误正文。22:50 的单次真实调度测试未观察到 `ensure` 执行，平台也没有新增这一轮的运行记录。随后已通过原生工具恢复每日 06:30，下一次为 2026-10-09 06:30。云端失败日志无法从现有接口取得，需要用户在平台查看详情后继续排查；没有变更账户权限或绕过审核。

## 新 Bot 验证状态（2026-10-09）

`100.71.234.37` 已完成用户的 Tailscale SSH 身份复核，并部署同一版本的适配器和恢复守护。Gateway 健康检查通过；适配器无凭据访问返回 401，带独立密钥的模型列表和文本回复返回 200。CPA 已通过配置热加载发布 `grokbot-2`，同时保留 `grokbot`；SSE 返回 200、预期回复及 `[DONE]`，没有重启 NAS 容器。

受控结束新 Bot 的 Tailscale 和适配器进程后，守护自动启动了新进程，Tailnet 节点身份与 IPv4/IPv6 地址保持不变。SSH 在严格主机密钥校验下连接成功，适配器健康、持久身份和开机入口检查均通过。Tailscale 已从 `/usr/local/libexec/grokbot/` 运行，使用 `--statedir=/var/lib/tailscale`。

新 Bot 的主 Agent 已通过平台原生例程工具登记 `tailnet-cpa-grokbot-2`，名称为“Tailnet 与 CPA 每日恢复（grokbot-2）”，计划每天 06:30（Asia/Shanghai），规格见 [daily-recovery-grokbot-2.json](daily-recovery-grokbot-2.json)。Transcript 的 `automation-changed / created` 事件和原生工具保存结果确认创建成功；正常且无恢复动作时静默，需要通知时发到新 Bot 的当前聊天。旧 Bot 的例程保持不变。平台状态为“已启用，从未运行”，首次计划在 **2026-10-10 06:30**。原生工具没有手动触发云端例程的功能，因此没有用当前聊天执行命令替代云端验收。**创建成功不代表云端执行通过，新例程尚未完成一次云端执行验收。**

未执行整台新 Computer 的重启或销毁重建测试。平台镜像重建仍依赖 Computer 内的 `recover.py ensure` 恢复入口；恢复脚本不会重新注册 Tailnet 身份。
