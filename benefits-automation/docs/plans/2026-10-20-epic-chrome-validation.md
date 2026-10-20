# Epic 原版 Chrome 只读对照

## 范围与决定

- 用户授权先验证原版、有界面 Chrome 与持久登录会话的方案。
- 在 NAS 侧沿用现有账号和 Epic 的 DMIT 路线；独立 Chrome profile 保留后续同环境复核能力。
- 使用官网下载的原版 Google Chrome 稳定版，在独立虚拟显示运行；不覆盖 UA、设备属性或 COOP，不调用验证码视觉模型。
- 正式 Camoufox profile、身份、订单 journal、调度及 delivery 保持。诊断走现有运行器、平台锁和浏览器锁，结果独立分区。
- 本次不领取、不支付。读取商品和官方结算页面；提交、quick-purchase 与未知支付写入在网络层阻止。
- 不恢复已按用户要求删除的平台回归，不以离线测试代替现场结果。

## 验收标准

- 记录实际浏览器版本、显示方式、账号登录与代理使用情况。
- 对照同一未拥有游戏的商品页、商店资源响应和零元结算加载，保留失败阶段与脱敏证据。
- 明确区分浏览器启动、Cloudflare 通过、账号已登录、结算可用和真实领取；本次不验收最后一项。
- 结束后确认 Chrome、显示与临时诊断进程已回收，正式订单记录及配置未改动。

## 进度

- 已核对部署、旧计划、当前运行数据与浏览器锁入口。NAS 无桌面 DISPLAY；现有官方 Chrome for Testing 153 可运行，官方稳定渠道当前返回 155.0.8059.84，正在准备独立版本。
- 与用户 MacAir 的对照限制：同名 DMIT 不等于已确认相同实际出口；NAS 虚拟显示的图形环境与物理 Mac 不同。跨浏览器复用账号登录 Cookie 也不等于 Chrome 自身新登录。

## 实测结果（19:46）

- 使用 Google 官方 Linux 安装包解出的 **Google Chrome 155.0.8059.84**，未全局安装；独立 Xvfb 显示、浏览器沙箱启用，`navigator.webdriver=false` 来自浏览器默认行为，未注入覆盖。
- 启动准备阶段两次遇到 Chrome Unix socket 临时路径过长、一次遇到 Firefox cookie 时间单位转换问题；均发生在访问站点前。改用 `/tmp` 独立短目录，按当前 Firefox 存储的毫秒时间转换后，正式访问启动正常；没有为此修改业务运行器或正式 profile。
- 首轮 `e9ecbf89-...` 商品 200、独立结算 403，但未固定同一路线。现场发现正式规则优先按 **Camoufox 程序路径**转入机房组，该组当前选中 DMIT；Chrome 没有命中这条规则。因此撤出首轮作为同出口对照的证据。
- 从当前正在运行的代理配置读取唯一 DMIT 节点，建立只绑定 loopback 的独立临时 Core，所有流量固定该节点。全局规则和选择器未改动；实际连接读回确认商店、hCaptcha、Talon 与 Cloudflare 验证域均经过 `EpicChromeDMIT`。

### 有效对照：`f67a0062-32d6-441d-9dfc-493460b9e5b9`

- 原账号登录 Cookie 导入新的 Chrome profile；未导入 Cloudflare/hCaptcha 挑战 Cookie。
- Agent A 商品页在约 **7.3 秒**出现 Get 与 Add to Cart，`isloggedin=true`，本轮商店资源 403 为 **0**。
- 正常点击 Get **一次**后，页面出现可见 hCaptcha；没有调用 SDK 或视觉模型继续答题。
- 独立官方 `/purchase?offers=...` 先 307，随后主文档 403，响应明确带 Cloudflare challenge。可见检查框正常点击一次后，继续观察约 **90.6 秒**，仍为 `Just a moment...`；未读到零元结算总额。
- 支付服务响应、confirm-order/challenge-order/quick-purchase 请求均为 0；未返回订单、未领取。
- Chrome 原生观测：Linux UA、平台 Linux x86_64、en-US、Asia/Taipei；**WebGL/WebGL2 均不可用**。这是可复现的 NAS 图形环境差异，尚未证明是验证失败的原因。
- 正式身份、订单 journal 与 Epic 配置摘要保持一致；诊断结果保存在私有 run 目录 `chrome-validation.json` 和日志/截图中。

### 持久登录复核：`c38f0eee-2cdb-47a4-888f-4222a9892f21`

- 关闭后重启同一 Chrome profile，未再次导入 Cookie；登录状态仍有效，Agent A 商品约 **7.4 秒**可用，实际路线仍为独立 DMIT。
- 本次只读取商品，不再次点击 Get、不进入结算；结果为 `persistent_session_ready`，不表示领取成功。

## 结论与验收边界

- 原版有界面 Chrome、持久 profile、账号登录和商品页面读取均已实测；**结算挑战仍未通过**。当前证据不支持仅换浏览器即可恢复领取，也不能将失败唯一归因于 Camoufox。
- hCaptcha 出现本身不等于账号封禁；独立结算 Cloudflare 挑战持续未通过是当前实测阻塞。缺少正常图形能力、网络/会话及其它站点风险信号的具体因果仍未确定。
- 未进行新订单、未调用视觉模型，未恢复平台回归；正式任务和自动领取能力仍保持未验收。
- 收尾核验：两轮 Chrome/显示进程均已退出，独立 Core 的两个端口均已关闭，浏览器清理标记已移除；正式状态摘要、主线他人两处启动文件摘要保持一致。保留独立 Chrome profile 与私有诊断记录供后续必要复核。
