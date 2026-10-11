# M1 Mac 阅读验证

日期：2026-10-11，Mac 客户端 0.4.0 / build 15。

## 实现

- 新增 Memos 笔记、全文阅读入口；日报正文与执行记录使用服务端 variant 分开查询。
- 公共头、详情、块、依据与加工状态采用独立解码模型，content ID 与 record ID 不混用。
- 正文固定 revision，按 next_after 分页，原样拼接后统一解析 Markdown；未知 schema/format 不进入正常阅读。
- 搜索显示正文命中摘录，加载到服务端 ordinal；跨分块查询继续加载，通过 Unicode scalar 偏移和 Foundation 原文位置滚动到实际命中段。支持停止自动定位。
- 409、404、头版本/状态改变清理旧派生数据；网络核对失败明确提示，旧响应不能覆盖新对象或新筛选。每 30 秒、应用重新激活及用户操作时核对头，不新增永久正文缓存。
- 原件依据校对输入与当前 hash；附件复用认证下载和 SHA-256 校验，保存前后核对内容状态。
- 内容整理状态与采集状态独立展示任务、对象、失败原因和来源覆盖。

## 自动化

`cd apps/mac-client && swift test`：18 项通过，其中 10 项阅读回归、5 项既有 Google 适配、3 项微信详情。

阅读测试包括合成 fixtures 解码、56 块 Unicode/Markdown 原样拼接、中文跨页边界搜索、字节预算产生的短页、opaque cursor/去重/筛选重置、快速切换请求竞态、空正文、非 ready 与未知格式、409/404、网络失败、依据版本变化、摘要/附件/依据的新版本替换、Markdown 标题/列表/引用/链接及高亮。

`bash -n apps/mac-client/build.sh`、`python3 -m py_compile apps/mac-client/install.py`、`git diff --check` 通过。

## 真实服务与安装

`/Applications/Personal Data Hub.app/Contents/MacOS/PersonalDataHub --reading-smoke` 使用既有 Keychain viewer 凭据，禁止凭据授权弹窗，只输出数量与校验结论，不输出正文或凭据。分别选取笔记、日报、执行记录最近 30 项中最长的就绪正文，读取全部块、依据与原件并比较完整正文；查询正文末尾片段并定位服务端命中；可用的小附件下载后校验并删除临时文件。

本轮真实服务检查：笔记 1,022 字 / 1 块、日报 709 字 / 1 块、执行记录 15,571 字 / 2 块，均与归档原件正文一致，依据与当前原件 hash 一致。末尾搜索分别定位到 Unicode scalar 偏移 982、669、15,532，均超过首 500 字预览。日报及执行记录附件 SHA-256 通过。

已通过 `python3 apps/mac-client/install.py --viewer-only` 更新原 `/Applications/Personal Data Hub.app` 并打开窗口。此路径沿用固定证书、Keychain、已安装资源和应用身份；不重新注册登录项、迁移采集组件或配置权限。更新前后两项采集 launchd plist、固定凭据助手、collection.tar.gz、collection.json 和 install-agents.py 的 SHA-256 均相同，严格代码签名验证通过。上一版保留为 `/Applications/Personal Data Hub.previous.app`，安装 ZIP 位于原 `apps/mac-client/dist`。

已通过实际 UI 检查笔记列表、真实 Markdown 正文、全文搜索命中与正文高亮、原件依据展开及“与当前原件一致”结果。私有真实正文和 UI 截图不提交仓库。

## 验收边界

- 本轮没有编辑或删除用户的真实原件。真实来源变更到 Mac 的完整联调仍需在可丢弃样例上验收；客户端清理与竞态行为已经通过合成 HTTP 响应测试。
- 全量打包因本机缺少仓库外 Google Desktop 配置停止；没有新建、替换或导出密钥。此次采用已安装资源的查看端更新路径，Google 继续使用原 Keychain 配置。
- 后台历史整理仍由服务端队列推进。列表就绪数量、采集健康和阅读就绪属于不同检查，不据此宣称全部来源加工完成。
