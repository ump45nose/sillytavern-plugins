# 拆除网络流量与 Token Monitor 及极简剩余流量接入

## 范围

1. **Token Monitor 拆除**：
   - Token Monitor（宿主机 17321 端口独立服务）本身已经是持久化采集与数据存储的完整闭环，不作为 Hub 或 Usage Monitor 的镜像/聚合对象。
   - 停用并移除 `apps/usage-monitor` 对 Token Monitor 的数据读取与日报聚合依赖，从根包 workspace members 移除该独立应用。
   - 清理 Hub 中遗留的 Token Monitor 代理配置与文档残留。
2. **网络流量复杂采集拆除**：
   - 彻底废除基于秒级轮询 Mihomo `/connections`、本地 SQLite 聚合、滚动 30 天 AI JSON 导出的复杂网络流量采集链路。
   - 停止 NAS 端的 `shellcrash-traffic-collector.service`、`shellcrash-traffic-report.service/.timer`、`shellcrash-traffic-ai-export.service/.timer`。
   - 移除 Hub 中的 `network_ingest.py`、`ingest-network` CLI、`traffic_hourly` / `collector_gaps` / `collector_meta` 事实表入库及 `shellcrash` 来源策略。
   - 移除 Hub `display` 与 `server` 中的 `network` 模块及 `/api/v1/network` 端点，业务来源明确收窄为 5 类（CRM/微信、Skysight、Plaud、健康、账单）。
   - 清理 `agents/nas/shellcrash/` 中的流量采集脚本，保留配置同步脚本 `shellcrash-subboost-refresh.sh`；清理 `agents/mac/network/`。
3. **极简剩余流量读取**：
   - 网络流量无需复杂的实时连接监听与分类事实表，只需读取 DMIT 订阅链接 `https://us17.dbxzs.com:7677/clash/ewomxzdnypreokt9` 的剩余流量。
   - 通过 HTTP HEAD/GET 获取 `Subscription-Userinfo` 响应头（包含 `upload`、`download`、`total`、`expire`），直接计算剩余配额及使用百分比，提供秒级只读查询工具与接口。
4. **SubBoost 刷新间隔梳理**：
   - SubBoost 内部由 `autoUpdateInterval` 控制各订阅的上游刷新周期，最小支持 0.1 小时（6 分钟）。
   - 宿主机已有 `subboost-update-subscriptions.timer` 每 6 分钟执行一次轮询，当前聚合订阅设置为 43200 秒（12 小时）。
   - 记录缩短刷新间隔的操作方式（Web UI 调整或数据库直接修改）。

## 关键决定

- **保留原系统闭环**：Token Monitor 容器继续作为独立应用稳定运行，只切断 Hub / Usage Monitor 的冗余采集。
- **采集链条最小化**：删除整个 `traffic_hourly`、SQLite 采集器及 Mac 采集 Agent；新的流量查询仅做一次轻量 HTTP 头部读取与解析，不落库、无死循环轮询。
- **平滑演进与验证**：历史 `traffic_hourly` 记录保留在数据库作为冷数据不物理删除；查询与概览不再包含 network 模块；集中验证 5 类业务来源不受影响。

## 验收标准

1. `curl -sI` 或极简 reader 能成功解析 DMIT 订阅的 `Subscription-Userinfo`，正确计算出总流量、已用流量、剩余流量及到期时间。
2. Hub 配置与来源校验拒绝 `shellcrash` 适配器；`display.overview()` 与 `trends` 默认不包含 `network` 模块；旧的 `ingest-network` 入口已移除。
3. 隔离测试中 CRM、Skysight、Plaud、健康、账单 5 类业务仍正常入库与查询，既有测试回归通过。
4. SubBoost 刷新间隔机制明确，给出清晰的调整方案。

## 实施进展与验证

- **代码拆除与重构**：
  - 删除了 `src/personal_data_hub/network_ingest.py` 与 `checks/mac-network-test.py`。
  - 清理了 `source_policy.py` 中的 `shellcrash` 来源适配器。
  - 清理了 `collectors.py` 与 `runner.py` 中的 `shellcrash` 及 `traffic_hourly` 分支。
  - 清理了 `display.py` 中的 `network` 模块、`traffic_hourly` 预览卡片、度量统计和 `network()` 查询方法。
  - 清理了 `processing/metrics.py` 中的 `traffic_hourly` 聚合规则。
  - 更新了 `server.py`：移除旧 `/api/v1/network`，将 `trends` 默认模块收窄为 `health,social`；新增极简 `/api/v1/traffic` 与 `/api/v1/network/traffic-remaining` 只读端点。
  - 更新了 `cli.py`：移除 `ingest-network`，新增 `hub traffic-remaining [--url URL]` 命令。
  - 更新了 `pyproject.toml`：移除 `apps/usage-monitor` workspace 成员与源定义。
  - 更新了 `deployment/config.example.json`、`mcp.app.yaml` 与 `README.md`。
- **极简剩余流量验证**：
  - 新增 `src/personal_data_hub/traffic_remaining.py`，实测 `curl -sI -X HEAD` 及 `hub traffic-remaining` 均在毫秒级正确解析并输出 300GB 总配额、已用 66GB、剩余 234GB（22%）及 2027-08-01 到期信息。
  - 编写并执行单元测试 `checks/traffic-remaining-test.py`，全部 3 项测试通过。
- **既有业务回归验证**：
  - `checks/source-cleanup-test.py`（3 项测试全部通过）：旧配置与旧适配器拒绝、通用入库限制、5 类保留来源正常写入与查询、`network` 等已退出来源被严格拒绝（422）。
  - `checks/display-smoke.py`：通过。
  - `checks/p1-repair-test.py`（8 项测试全部通过）：CRM 事务归档、发布锁、附件与阅读内容正常。
  - `checks/query-status-smoke.py`：通过。
  - `checks/daily-push-smoke.py`：通过。
