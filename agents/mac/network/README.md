# Mac 代理流量采集

代码与 Python 运行时随 Personal Data Hub 客户端打包，使用固定 `--collect-network` 入口运行。客户端设置提供启停，关闭窗口后 launchd 继续采集；`--install-network` 是显式启用入口。默认不会启用 TUN、系统代理或修改 Proxifier 路由。

从 Clash Verge 的运行配置发现 Unix socket 或本机 TCP 控制器，每秒仅读取 `/connections` 元数据，复用 NAS ShellCrash 的维度和小时累计事实。排除内核自身的 Inner 连接，不记录请求正文、路径、订阅 URL 或代理秘密。代理未提供的应用名保留未知；域名不能当作应用归属依据。

私有配置、`traffic.sqlite3`、状态和待传队列位于 `~/Library/Application Support/PersonalDataHub/Network`，不会入包。固定设备 ID 在首次启用时创建，后续安装与重启保留。默认沿用该设备活动采集的 NAS SSH 路由。

事实与待传版本同事务写入，每分钟通过 SSH 调用 NAS `hub ingest-network`。批次哈希与落库回执匹配后，仅清除已确认版本；同一事实的新版本继续等待上传。服务端按 `network-mac-<device_id>` 隔离来源，按稳定小时维度覆盖累计值，重试不重复累加，旧批次不能降低已提交计数。

首次启动仅从当前计数建立基线，采样前的流量不归入当前小时。重启、休眠和 API 断线记录缺口，恢复时建立新基线。每秒活动连接轮询仍可能漏记短连接与关闭尾部字节；这一口径不等同于运营商账单。不同代理层分别统计。

离线验证：`PYTHONPATH=src:apps/usage-monitor/src python checks/mac-network-test.py`，使用包含 SQLAlchemy 的项目 Python。真实后台读取：安装客户端的 `--collection-check-network`，只返回可读性与计数，不输出域名或路由明细。
