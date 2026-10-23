# Personal Subscriptions

独立订阅业务：采集 → SQLite → HTTP / MCP。管理同一服务的多个账号、个人／公司付款和免费资源；Hub 是消费者，不保存订阅主记录。

AI 额度复用 Token Monitor 的鉴权 HTTP 接口；网络套餐读取 SubBoost 的所有者限定只读元数据接口，逐个原始来源提供总量／上下行／到期。缺失字段保持未知，本地 ShellCrash 流量不参与计算。普通会员只管理资料与周期。Muse、Manus、Hark 自动采集暂缓，不安装 CodexBar。

## 数据与接口

金额为原币十进制字符串；null 是未知，0 是免费。payer=self 的有效记录才纳入个人费用，company 不计个人支出；unknown 需要人工确认。不自动换汇。价格与付款周期人工维护，不推进或推断实际扣款。实际账单归 Personal Records。

订阅字段见 `Subscription`；Binding 明确指定 collector/provider/account，可保存来源现有邮箱与配置名用于凭据轮换后的唯一匹配。账号不按服务名合并，不确定则返回 account_requires_binding。

- `/api/v1/subscriptions`：GET offset/limit/category（默认50，最多200）；POST 创建。
- `/api/v1/subscriptions/{id}`：GET 详情；PATCH 部分更新；DELETE 删除。修改和删除需要 `If-Match: <version>`，陈旧版本409，缺版本428。
- `/api/v1/sources`：最近采集发现的非秘密来源账号，供绑定；查询不访问供应商。
- `/healthz`：SQLite检查；`/mcp`：八个对应的业务读写工具。

额度只保留最新成功读数；失败更新状态但不覆盖读数。observed_at 为来源实际观察时间，last_success_at 是本服务成功处理时间，两者不能替代。优先采用来源刷新周期／过期标记；没有规则时900秒过期。重绑或停用清理旧额度，采集中删除／重绑不会被旧请求恢复。

HTTP 使用不同的 SUBSCRIPTIONS_API_READ_TOKEN / SUBSCRIPTIONS_API_WRITE_TOKEN（支持 _FILE）；MCP 复用 mcp-platform OAuth 及读写授权。凭据、SQLite、备份及 OAuth 状态不进入 Git。

## 品牌与购买入口

`service_key` 选择独立于额度绑定的品牌；`theme_color` 为可空的 `#RRGGBB`，留空使用品牌默认色；`subscription_url` 是可空的 HTTP(S) 购买／续费页面地址，不接受 URL 用户名和密码。不会抓取用户填入的网址。`icon_url` 是只读的同源 PNG 资源路径。旧记录读取时自动补齐空字段，无数据库迁移。

`GET /api/v1/subscriptions/brands` 和 MCP `list_subscription_brands` 返回内置品牌目录。`GET /api/v1/subscriptions/icons/{service_key}.png` 使用现有 HTTP 读鉴权，Hub 通过设备鉴权转发同一路径。25 个品牌图标随服务打包，无运行时图床依赖；素材来源、散列和许可证在包内 `assets/`。88VIP 使用文字标识，购买入口未确认时保持为空。

## 运行

Python3.12+，安装 server extra。SUBSCRIPTIONS_DATABASE 默认 /data/subscriptions.sqlite；SUBSCRIPTIONS_COLLECTORS_FILE 指向私有 JSON，token_monitor/subboost 各含 url/token；仅供采集命令读取。

```sh
personal-subscriptions serve
personal-subscriptions collect
personal-subscriptions status
personal-subscriptions backup --destination /private/subscriptions.sqlite
```

采集由 NAS systemd timer 每5分钟调用，文件锁阻止重叠。HTTP/MCP 与采集共用同一数据库和业务模型，无内部后台调度。备份通过 SQLite backup API，另备份私有配置及 OAuth 状态；恢复须停止写入。
