# 酒馆真实调用采集

范围为独立 RP 扩展、中心上报接口和生产来源配置。RP 保持酒馆直连与人工管理，不主动请求模型或模型目录，不进入网关自动提降权。

复用原生 fetch 生成请求，在请求开始时固定当前 profile、实际地址、协议和模型。只观察原生消费者读取的响应，保持请求及响应字节；保存耗时、首字、上游 Token 和完成/失败/取消/未确认终态，不保留聊天正文。流式终态按 SSE 正文识别，不依赖响应头。浏览器离线队列逐条确认；开始回执不能移除稍后产生的终态，上报失败不阻止生成。

采集复用中心已有用户/profile 来源关系，不自动建立管理绑定，避免改变既有暂停拦截条件。原生配置保存和连接同步流程保持原样。实际请求地址变化时由中心保留待关联。

## 验收与完成

- [x] 类型检查与 50 项测试通过；补充流式元数据、无终态、错误、取消、原请求不变和离线并发回执检查。
- [x] 隔离原生酒馆对自有模型发起 5 次生成：3 成功、1 失败、1 取消，中心 5 条；断网上报保留与恢复通过，没有额外模型请求或公网 RP 请求。
- [x] 独立扩展 1.1.0 已安装到 fn 生产。两个用户配置中心地址、限定凭据与设备名，其余原生字段逐项核对一致，绑定数量仍为 0；刷新页面启用。
- [x] 中心近 90 天回填 122 条原生历史生成元数据；历史站点与终态缺失，保持待关联/未知，不参与成功率。本地 Token 估算单列。

中心代码与回执位于同工作区独立 ai-resource-center 项目，见 `docs/plans/2026-10-15-rp-call-collection.md`、`docs/verification/sillytavern-calls.json`、`docs/verification/sillytavern-production.json`。测试脚本 `scripts/verify-resource-center-calls.mjs` 只面向隔离中心 18329、validation 酒馆及 Docker 网络中的 `fixtures/resource-center-model.mjs` 自有模型，不能改为生产 RP 地址运行。

生产扩展目录 `/vol2/1000/Docker/sillytavern/extensions/ai-resource-center`。升级前设置及扩展备份 `/vol2/1000/Docker/ai-resource-center/backups/20261015-rp-calls-063344`。回退采集恢复旧扩展，按需恢复 aiResourceCenter 集成设置；不覆盖升级后其他酒馆设置修改。中心停机时既有直连继续工作。
