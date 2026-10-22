# 订阅与网络套餐：来源边界及复用调查（2026-10-22）

状态：用户已选择 Wallos 作为 AI、网络及其他订阅的统一台账。固定版本源码和
隔离假数据验证已完成；适合台账职责，原版 API 有接入前需要修复的缺口。
尚未部署或迁移生产业务。账号同步仍由来源采集器承担。

## 本轮范围与验收

- 固定 Wallos v5.10.1（573010f72bca91556141ce822efa443f3b72591f），核对 API、
  账号隔离、字段更新、币种／周期、停用、来源绑定及并发语义。
- 在不接入生产网络、凭据和数据的临时容器中验证假数据 CRUD；记录失败和局限。
- 明确 Wallos、Token Monitor、SubBoost、usage-monitor 和 Hub 的最终归属，
  给出消除重复主记录的迁移步骤。评估阶段不修改生产服务或新增常驻入口。
- 验收产出：有证据的适用性结论、字段／接口缺口、可执行的接入顺序及待确认事项。

## 边界判断

独立性按授权状态、采集调度、来源事实和长期业务规则划分。登录／令牌续期、
平台适配、失败处理和账号归并属于来源应用；Hub 保留设备认证、来源凭据代持、
短期缓存、展示合并、提醒及写代理。独立业务归属不要求每个页面增加一个容器。

- AI：优先复用已经运行的 Token Monitor 账号采集和额度同步。其实际付费订阅
  另有共享文档，价格仍是手动记录；不能把登录后额度当成已取得实际付款和续期。
- 网络：优先核验已部署 SubBoost 的原始订阅与 subscriptionInfo 输出；
  Sub-Store 可作为同领域参考，不因名称相同另起一套重复采集。套餐总量、
  供应商已用量、到期／重置从供应商接口／订阅信息取得；缺失仍未知。
- 本地网络流量：保留 ShellCrash／usage-monitor，展示本地上下行和趋势。
  本地路由器流量与供应商跨设备计费流量分开；不再用前者冒充每个套餐的消耗。
- 统一台账：选用 Wallos。官方资料未证明
  它们能通用登录所有第三方商家采集。其他平台的自动取数需要按实际名单核验
  已有接口／适配器；邮件、账单识别同样属于业务侧能力。
- 每条订阅只保留一个主记录，最终全部归 Wallos。现有 Token Monitor 费用资料
  在切换时迁入或保留可核对的历史，再替换原写入口，不双向维护价格／周期。
  供应商事实、实际费用和手动补充的来源需要明确，避免手动值覆盖后失去依据。

## 候选与证据

1. Token Monitor（现有部署）：本地 README.zh-CN.md 的“订阅资料”明确手动记录实际
   费用；docs/API.md 的 GET/PUT /api/subscriptions 为跨设备共享账号订阅文档，
   provider 账号凭据与额度采集另有独立 registry。保留该版本来源已有归并机制。
2. Wallos：通用自托管订阅台账，周期／预计付款、分类、多币种、通知、OIDC、
   Docker／SQLite 及 API；官方 releases 有持续发布记录。源码 API 目录含读取
   和 set_subscriptions 写入口，写入源码含新增／更新／删除路径。它的 OIDC 是
   登录 Wallos 本身，不是第三方商家自动采集协议。外部账号绑定、API 鉴权／
   更新语义及 Hub 代理集成仍须小范围实测后定型。
   - https://github.com/ellite/Wallos
   - https://raw.githubusercontent.com/ellite/Wallos/main/README.md
   - https://github.com/ellite/Wallos/releases
   - https://github.com/ellite/Wallos/tree/main/api/subscriptions
   - https://github.com/ellite/Wallos/blob/main/api/subscriptions/set_subscriptions.php
3. SubTracker：通用台账备选，Fastify／Prisma／SQLite，支持单独 API 部署、
   Wallos 备份导入、支付记录、AI 从文字／图片辅助录入及多币种／提醒。
   官方功能清单未证明有通用第三方账号登录采集。
   - https://github.com/Smile-QWQ/SubTracker
4. SubBoost：现有网络订阅来源，原始订阅管理、定时刷新及聚合；已核验的
   固定版本 YAML 路由向响应头传递 result.subscriptionInfo。能否取得每个供应商
   的套餐用量需要核验实际上游，不能因存在该字段就认定已有数据。
   - https://github.com/SubBoost/subboost
   - https://github.com/SubBoost/subboost/blob/4a69b494b46d095c965be58cf425fe35a2c1e524/local/app/api/subscriptions/%5Bid%5D/config.yaml/route.ts
5. Sub-Store：网络订阅管理／转换的同领域参考。当前已有 SubBoost，暂无替换依据。
   - https://github.com/sub-store-org/Sub-Store

## 固定版本验证结果

版本 v5.10.1，源码提交 `573010f72bca91556141ce822efa443f3b72591f`；官方镜像
`bellamy/wallos:5.10.1`，仓库摘要
`sha256:b12fc3f6456fa4879346d27f13c96011a1dce8d5285ef31fcec9323f2bac9854`。
镜像中的订阅读写 PHP 文件与该标签源码 SHA-256 相同。GPL-3.0。

临时容器 `wallos-eval-20261022` 采用 network=none、无端口、无挂载、UID/GID
82:82、cap_drop ALL、no-new-privileges、1 CPU／384 MiB／64 PID；仅运行初始化、
迁移与 PHP 内置 HTTP 服务，没有运行通知／汇率／更新 cron。通过正常注册流程
创建三个假用户；仅对容器内临时数据库取出假 API key 供测试，不读生产凭据。

完成 28 项行为验证，原始结果见
[`../evaluations/2026-10-22-wallos-api.json`](../evaluations/2026-10-22-wallos-api.json)。
这些验证同时包含正常行为与缺陷复现，不能理解为全部能力无缺陷。

| 项目 | 实测结果／影响 |
| --- | --- |
| CRUD、部分编辑 | 可用；只改价格保留名称、备注、周期、日期、币种 |
| 原币种 | USD、CNY、HKD、TWD 存在且可保留；未实测在线换汇 |
| 周期／状态 | 月、年、每三个月、停用／恢复、关闭自动续费可用 |
| 用户隔离 | 无 key／无效 key、跨用户读取／修改／删除及使用他人的币种被拒绝 |
| HTTP 错误语义 | 缺 key 等失败仍返回 HTTP 200＋success=false；Hub 必须映射业务错误 |
| 外部来源绑定 | 传入 external_id 仍返回成功但不保存；原生没有对应字段 |
| 并发版本 | 持旧快照并附 If-Match 的更新仍成功，覆盖较新价格；没有 CAS |
| 稳定标识 | 删除最大 ID 后，新建记录复用该 ID；仅按该 ID 绑定账号会串记录 |
| 输入校验 | 负金额被接受；非数字金额转成 0；frequency 无正数范围校验（源码核验） |
| 月末续费 | 2026-01-31 月付运行原生续费 cron 后得到 2026-11-03，发生日期漂移 |
| 一次性费用 | 数据库有 cycle=5，但订阅写 API 只接受 1–4，新增一次性费用被拒绝 |

金额存储是 SQLite REAL，接口不是整数分；桥接时按币种精度解析，不把 Token
Monitor 的 amountMinor 当原币金额。API key 是用户级读写凭据，没有独立只读
scope。Hub 后台使用 POST 表单携带 key，客户端仍使用现有设备鉴权，key 不进
URL、客户端或访问日志；生产期还需验证 Nginx/PHP-FPM 和现有 Authelia 的集成。
Hub 使用台账所属普通用户的 key，不使用用户 1 的跨用户管理能力。

固定源码证据：

- [读 API](https://github.com/ellite/Wallos/blob/573010f72bca91556141ce822efa443f3b72591f/api/subscriptions/get_subscriptions.php)
- [写 API](https://github.com/ellite/Wallos/blob/573010f72bca91556141ce822efa443f3b72591f/api/subscriptions/set_subscriptions.php)
- [续费日期推进](https://github.com/ellite/Wallos/blob/573010f72bca91556141ce822efa443f3b72591f/endpoints/cronjobs/updatenextpayment.php)
- [月费用估算](https://github.com/ellite/Wallos/blob/573010f72bca91556141ce822efa443f3b72591f/api/subscriptions/get_monthly_cost.php)

核验了 schema 和月费用源码：预计付款按当前价格／周期计算，不能替代历史真实
扣款，也不能据此声称过去已经支付。确认扣款继续来自 personal-records。
本轮没有在线换汇、OIDC 或真实账号联调，也没有验证全部 Web UI 行为。

现有 Token Monitor 持久化文档只读检查：4 条订阅（codex、grok、cursor、
antigravity），均为 USD 周期订阅，均有 binding，topUps 共 0 条。未导出账号标识、
邮箱或金额。Hub 自有 subscriptions／net_plans 先前检查均为空，迁移时需要重读。

## 选定的职责与接入方案

| 对象 | 唯一归属 |
| --- | --- |
| 全部订阅名称、原币金额、付款周期、预计续费、停用状态 | Wallos |
| AI 登录凭据、令牌刷新、账号识别及服务商额度事实 | Token Monitor |
| 网络订阅 URL、刷新、供应商总量／已用／到期事实 | SubBoost；实际上游缺失的字段仍未知 |
| 本地网络上传／下载和趋势 | ShellCrash／usage-monitor |
| 实际扣款流水 | personal-records |
| 设备鉴权、短期缓存、来源合并、提醒展示及写代理 | Hub |

统一台账不要求重写采集器。Wallos 是价格和续费等可编辑数据的唯一写入目标；
AI／网络的实时额度为只读关联数据，不周期性复制到 Wallos。付款日、套餐到期日
和额度重置日分别显示，不相互推断覆盖。Token Monitor 现有费用编辑入口需要
切换到 Wallos；不能保留两套各自可写的价格。若保留其原生费用视图，必须为
Wallos 的只读投影，且明确不等于实际账单。

为保留已约定的 App 编辑能力，建议在 Wallos 来源侧维护一组小而明确的补丁，
Hub 不建立第二个订阅业务库，也不在 Hub 重写续费规则：

1. 来源关联作为 Wallos 的结构化关系保存：订阅关联现有 Token Monitor 账号／
   SubBoost 原始订阅。复用 Token Monitor 已有账号 binding 语义，不能仅依赖
   跨平台不稳定的 accountKey，更不按工具名自动把多个账号合并。无采集器的
   普通订阅不需要关联。不把 JSON 塞入备注或按名称模糊连接。
2. 订阅 ID 不复用；增加来源端版本检查，Web UI 与 API 编辑均参与，陈旧写入
   返回冲突。金额／周期校验和月末日期推进在来源修正，不能只在 Hub 挡一次，
   否则 Wallos 自己的编辑页和 cron 仍会写出不同结果。
3. 预计续费规则明确保存周期锚点，跨短月后不丢失原付款日；服务商有实际日期
   时展示来源事实，不能用估算覆盖。一次性充值不伪装成月付；当前无此迁移
   数据，不为假设需求新增支付流水功能。

补丁在独立第三方源码仓库维护，固定上游版本并保留升级检查；仅变更上述实际
接入所需部分。无需新建通用采集框架或第二个订阅管理服务。若以后不维护这些
补丁，原版可作为人工台账，但不满足此处完整的 App 关联编辑要求。

Hub 当前 CNY-only、month/year 和整表替换接口无法无损承载四条现有 USD 记录。
接入时同步更新公开契约与原生客户端：保留原币种／frequency／状态；以单条操作
及版本冲突表达编辑，不能把未显示或不认识的 Wallos 记录当作应删除。月度合计
使用 Wallos 可验证且标明日期的汇率；汇率缺失时按币种列出，不冒充 CNY 总额。

## 后续实施顺序与验收

本轮完成评估与选型；以下为待实施事项，未宣称上线。

1. 在独立 Wallos 来源仓库维护最小补丁，针对上述实测缺口验证，包括月底／
   闰年续费、标识不复用、Web/API 冲突及来源解绑；现有账号识别单独核验。
2. 固定镜像部署独立 Wallos，按正式栈入口配置 SQLite／logos 数据与备份；Hub
   只访问其内部 API。Web 管理入口按现有 Authelia 接入。共享登录变更另列实际
   影响及操作时机；不为内部 API 新开公网入口。备份恢复与身份权限实测。
3. 只读核验 SubBoost 每个原始订阅的供应商信息；与本地流量分别提供。同步
   更新 Hub 与客户端接口，保持现有编辑能力并使错误、过期和未知状态可见。
4. 切换前重读所有来源，生成逐条映射和私有备份；完整迁移现有 4 条 AI 订阅及
   当时非空的 Hub 记录。绑定与币种核对后，关闭旧台账写入口，再启用 Wallos
   写代理；不以双向同步作为长期方案。
5. 验收 AI／网络／普通订阅的显示与编辑、额度来源、真实扣款标识、旧客户端
   行为和来源失败状态；删除 Hub 原订阅／套餐业务字段、存储、失效规则与旧
   模拟用量逻辑，仅保留必要的迁移记录与可核对历史。

尚未实测：生产 Wallos 部署／恢复、Authelia、汇率、供应商账号关联、现有全部
网络供应商的数据覆盖、App 写代理，以及上述建议补丁。没有迁移或改写生产数据。

## 调查方法和限制

使用 smart-search-cli；main_search 默认模型不可用，单次模型覆盖后广泛搜索
90秒超时，180秒重试遇上游流式响应错误。采用可用 CLI fetch 抓取官方仓库、
README、releases、API 目录及源码，并读取本机实际版本；未把模型生成的概述
当作证据。API 文档独立站和部分 raw 源码提取失败，使用可读取的 GitHub 页面
交叉核对。这里没有断言不存在其他通用采集器，只记录本次核验范围。

证据目录：/tmp/smart-search-evidence/20261022-hub-subscriptions。
关键命令示例：

```sh
smart-search fetch https://raw.githubusercontent.com/ellite/Wallos/main/README.md --format json
smart-search fetch https://github.com/ellite/Wallos/tree/main/api/subscriptions --format json
smart-search fetch https://github.com/Smile-QWQ/SubTracker --format json
smart-search fetch https://github.com/SubBoost/subboost --format json
```

固定版本源码通过 `git clone --depth 1 --branch v5.10.1
https://github.com/ellite/Wallos.git /tmp/wallos-eval-20261022` 取得用于镜像核对和
执行假数据验证。测试传输为容器内回环 HTTP POST；没有以直接数据库写入冒充
CRUD 成功。临时脚本 `/tmp/wallos-api-eval.py`，测试原始报告已随本文留存。
临时容器已删除，无临时端口、挂载卷或常驻服务；未变更正式 Compose、共享登录
及任何生产服务。正式 Hub 仍为 local/hub-api:5d85450。
