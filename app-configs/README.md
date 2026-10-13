# app-configs

按软件分类存放可公开的应用配置，用于备份与跨机迁移。

## 目录结构

```
app-configs/
├── deskflow/    Deskflow（Synergy 系鼠标键盘共享）Windows 服务端配置
├── grokbot/     Grok Bot 的 CPA 文本适配器与 Tailnet 恢复脚本
├── web-preview/ fn 局域网固定网页预览入口与交付 skill
└── subboost/    Android 代理与 Tailscale 共用 VPN 的订阅配置、构建和恢复
```

每个软件一个子目录，内含该软件的配置文件副本、说明文档和恢复脚本。

Grok Bot 的使用入口：[部署与验证状态](grokbot/README.md)、[安装、SSH 与恢复提示词](grokbot/PROMPTS.md)。

HTML 设计交付：[fn 固定网页预览](web-preview/README.md)。

手机组网：[SubBoost + CMFA 的 Tailnet 分流与接入](subboost/README.md)。

## 隐私说明

配置文件中包含内网 IP（192.168.31.x）、主机名（yuwk_home）与本地用户路径，均为局域网内信息，无凭据密钥，可公开。
