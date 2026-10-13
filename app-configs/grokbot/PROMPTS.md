# Grok Bot 安装、SSH 与恢复提示词

以下提示词按顺序发送给 Grok Bot。首次安装需要用户在浏览器完成 Tailscale 授权；已有部署的恢复直接使用第四步。

## 1. Mac 安装并登录 Tailscale

在 Mac 安装 Tailscale，并登录自己的 Tailscale 账号。终端检查连接：

```bash
tailscale status
```

确认 Mac 已出现在自己的 Tailnet 中。

## 2. Grok Computer 安装 Tailscale

发给 Grok Bot：

```text
在当前 Linux Computer 中安装并启动 Tailscale，只安装和配置 Tailscale，不修改 SSH、防火墙、代理、DNS 或其他网络配置。安装完成后运行 `sudo tailscale up`。如果需要浏览器认证，把登录 URL 发给我，不要代替我授权。
```

Grok Bot 会返回 Tailscale 登录认证 URL。在 Mac 浏览器打开该 URL，并使用与 Mac 相同的 Tailscale 账号完成授权。

## 3. 开启 Tailscale SSH

认证完成后，发给 Grok Bot：

```text
检查 Tailscale 是否已正常连接，正常则执行 `sudo tailscale set --ssh` 开启 Tailscale SSH。不要安装或配置 OpenSSH Server，也不要修改其他网络配置。完成后告诉我 Tailscale IPv4 地址和当前 Linux 用户名。
```

Mac 终端使用返回的地址和用户名登录：

```bash
ssh <Linux用户名>@<Tailscale-IP>
```

当前部署示例：

```bash
ssh box@100.103.12.86

# 新 Bot（CPA 模型名 grokbot-2）
ssh box@100.71.234.37
```

若 Tailscale SSH 返回身份复核 URL，由用户在浏览器完成授权。

## 4. 已有部署的手动恢复

这个提示词依赖持久目录中已有恢复脚本、身份、Tailscale 二进制和适配器私有配置；不能替代首次部署。

发给 Grok Bot：

```text
在当前 Grok Bot Computer 内，使用终端工具依次执行：
python3 /home/box/cli-config/grokbot/recover.py ensure
python3 /home/box/cli-config/grokbot/recover.py status

保留已有 Tailscale 身份和 Tailscale SSH 配置，不要重新登录或登出，不修改 DNS、防火墙、系统代理、Exit Node、OpenSSH 或其他无关网络配置。
如果系统负载较高导致检查超时，等待负载下降后重试，并报告实际结果。
如果脚本、已保存身份或私有适配器配置缺失，停止并报告缺失项，不自行创建新身份或获取新凭据。
完成后只告诉我恢复是否成功、Tailscale 状态、IP、适配器健康状态和开机恢复入口状态，不展示 token、state 文件内容或私有配置。
```

Tailscale 已在线时，也可以在 Mac 直接执行：

```bash
ssh box@100.103.12.86 'python3 /home/box/cli-config/grokbot/recover.py ensure'
ssh box@100.103.12.86 'python3 /home/box/cli-config/grokbot/recover.py status'

# 新 Bot（CPA 模型名 grokbot-2）
ssh box@100.71.234.37 'python3 /home/box/cli-config/grokbot/recover.py ensure'
ssh box@100.71.234.37 'python3 /home/box/cli-config/grokbot/recover.py status'
```

镜像重建后若 Tailscale 尚未启动，先通过 Grok Bot 的 Computer 终端执行恢复命令。

## 5. 每日恢复例程

完整任务提示词保存在 [daily-recovery.json](daily-recovery.json) 的 `prompt` 字段，计划为每天 06:30（Asia/Shanghai），正常且没有恢复动作时保持静默。这个 JSON 是配置规格，需要通过平台原生 `UpdateRoutine` 登记或更新；复制文件本身不会创建云端任务。

新 Bot（`grokbot-2`）使用 [daily-recovery-grokbot-2.json](daily-recovery-grokbot-2.json)；其任务名称与旧 Bot 分开，恢复命令仍在各自的 Computer 内执行。

每日例程会唤起 Bot，可能消耗模型额度；Computer 内的后台守护只消耗系统资源。

**两个 Bot 的例程均已登记，但云端自动执行尚未通过验收。** 镜像重建后目前使用第四步手动恢复，旧 Bot 的验证记录见 [README](README.md#验证状态2026-10-08)，新 Bot 的记录见 [新 Bot 验证状态](README.md#新-bot-验证状态2026-10-09)。
