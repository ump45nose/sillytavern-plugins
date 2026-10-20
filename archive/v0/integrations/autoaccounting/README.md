# AutoAccounting 接入

正常采集使用官方应用的账单 Webhook，官方 PR [#1390](https://github.com/AutoAccountingOrg/AutoAccounting/pull/1390) 已合入。`upstream.lock.json` 记录实际核对的官方提交和协议。

聚合端兼容单个 `BillInfoModel` JSON 的 HTTPS POST、原 Bearer 和 HTTP 2xx 回执；重复推送按账单 ID 和内容哈希归档。无需修改官方应用、替换 APK 或另建手机采集器。

`app/`、`nas-export.patch` 是迁入的自有导出源码资料；`hub-deletion-outbox.patch`、`build-receipt.json` 是此前开发的可选删除扩展，未启用，不要求安装。官方当前导出没有主动删除通知，完整性未知或窗口缺失时不推断删除。
