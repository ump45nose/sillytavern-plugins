# Rewards 原生受限能力

## 已实现模式

所有模式只通过同一个 run.py 入口运行，持有同账号锁和全局浏览器锁，受总 deadline 监督。latest 结果按 results/rewards/<account>/<mode>/ 分开，防止只读 snapshot 覆盖每日活动或完整任务状态。

- `--mode activities`：每日活动卡片，原有迁移功能
- `--mode snapshot`：只读当前 dashboard/flyout；不点击登录、领奖、目标或活动
- `--mode extra`：已有社交卡片/Explore 静态查询主题；先验证当次明确 unlocked 资格，再一次点击/有限查询，只读回确认。当前目标设置暂为 blocked；完整手动兑换目标设置/授权恢复属于待补齐能力，不是永久删除，不开启自动兑换
- 默认 `--mode full`：原生顺序编排，必须提供明确启用的 capabilities.json；不导入上游 Main。未实现或缺可信调用方的已请求能力会明确 pending

上述模式均需显式 `--execute`；这里只开发/离线测试，没有使用真实 Cookie、会话或网站动作。`daily=complete` 或 snapshot 返回不能代表完整 Rewards 全部完成。

## 小型运行依赖

`REWARDS_ROOT` 是安装 patchright 1.61.1 的目录；本目录的 package-lock.json 可用于 npm ci --ignore-scripts。浏览器二进制另行安装，用 run.py 的 --browser-cache 指定。不关闭 Chromium sandbox。

唯一账号会话：runtime-root/state/rewards/<opaque-account>/storage-state.json，最多 1 MiB，owner-only。无自动登录，无 SQL 账号扫描、无外部通知。遇到可识别的登录/挑战页返回 human_required。页面/字段异常返回 unknown；没有自动解验证码。

## 受控 parser 构建

extra 运行时直接加载 vendor/rewards-parser 中的精确独立 React parser（生成 JS 约26KiB），零 runtime require/import；原 TypeScript、source map、完整 GPL-3.0 许可证及 commit/compiler/hash 证明同时保留，不执行上游 Main。不需要下载/安装上游168个依赖，也不需要 REWARDS_UPSTREAM_DIR。

下列完整构建仅用于开发者核验 parser 可重复生成，不是运行前提：

```sh
python platforms/rewards/build.py /path/to/exact-upstream /path/to/empty-build --install-build
node tests/rewards_build_contract.cjs /path/to/empty-build
```

精确上游：TheNetsky/Microsoft-Rewards-Script v4.3.2、提交 f61f4e982bbb435f37133bed0dc5b4c582ed1e73。源码文件均由 build-source.json 固定 SHA256；依赖以其 package-lock.json 安装，禁用安装 scripts 和浏览器自动下载。仅独立 parser 成品、原源码和许可证进入本仓库；完整输出/依赖缓存不进本仓库。

唯一入口补丁位于 build.py 的 patch_entry：去掉导入即运行的 CLI main 定义和调用及对应未用 import；保留导出的 MicrosoftRewardsBot 和 executionContext。它不会将 Main 改造成安全运行器，不能直接调用。

编译调整：原 tsconfig 的 commonjs + bundler resolution 与 TypeScript 6 组合不兼容；尝试 Node16 module/resolution 后，p-queue 的 ESM 导入报 TS1479。最终使用 `--module Node20 --moduleResolution Node16`，匹配本轮 Node 24.19.0 对 require(ESM) 的支持，编译通过。没有 suppress 类型错误或 noEmitOnError 绕过。每次 benefits-build.json 记录 source commit、具体 Node/TypeScript 版本、编译参数、补丁说明和完整 dist hash。

本轮开发核验曾按上游锁安装168个包、TypeScript编译、资源复制，全部通过；这些依赖不属于最终原生日常运行需求。离线 contract 在模块导入前阻断 Node 网络入口和 subprocess，验证移除自主 main 后能导入，及真实 React parser 的合成页面。它不证明旧 NAS local/rewards:4.3.2 与此候选源码一致。

## 内存与输出

HTML 仅在浏览器侧限定 2 MiB 后传回解析，flyout 响应在浏览器侧流式读取上限 1 MiB。只返回固定业务分类，不保存完整 HTML、截图、账号字段、原始 server payload 或无限历史。最多300条输入记录/30个选定活动，主题最多2个查询；确认轮询和等待均有限。popup、verification page、context、browser 随阶段关闭，禁止浏览器任务并行。

有限输入不等于整个 Chromium 的硬 RAM 上限；真实浏览器和网站尚未验收。

## 完整 Main 的未决设计

官方 Main 包含账号/.env 发现、自动登录、多种浏览器/APP token路径、SQLite写入、HTTP写重试、通知以及 process.exit。简单配置不能全部关闭这些影响。要保持原完整 Main，至少需要多个版本绑定兼容替换；用户已明确要求以独立能力重写并保留完整合理业务与障碍恢复，不继续堆叠大范围 Main monkeypatch，也不靠减少能力降低内存。完整对照和待补齐项见 ../../docs/REWARDS_PARITY.md。当前不运行原 Main，不声称完整 Rewards 已迁移。


## 第三轮：独立搜索与可恢复障碍

新增 --mode desktop-search / mobile-search：复用当前账号各自保存的会话，独立严格读取 desktop/Edge/mobile quota，序列化搜索、延迟入账只读确认、停滞退出、上限预算、未知/倒退 counter 停止；Enter超时先读回，绝不盲目重放。默认最多100次搜索、连续3次无进展停止，均受总 deadline。默认30秒间隔；实际搜索建议显式配置足够 --timeout，不会自动延长上限。

mobile-search 需要 storage-state.mobile.json 及 native-config.json 的 mobile 设备侧配置（isMobile=true 和已有稳定 userAgent；可提供viewport/locale等），缺失就明确报告 mobile_device_profile_required，不用桌面状态冒充移动完成。desktop 使用原 storage-state.json。只准有限浏览器 context 参数，不准借配置开启录屏、权限或跳过TLS。

native-config.json 可配置 search.maxSearches/stagnantLimit/delayMs/readbackAttempts/readbackDelayMs/queries/clusterSearch/clusters，以及 region。clusterSearch 是词组聚类，**不是浏览器并行**，故没有为省RAM删除。当前本地词库与显式配置词组已实现；完整远程词源/随机结果访问/额外搜索等仍按能力矩阵逐项补齐，不声称被替代或完成。

obstacles.cjs 为typed探测与恢复计划，common/intervention_signal.py把子进程信号转为待审批checkpoint；文件不等于授权。登录/验证码/新条款/年龄/安全设置/目标设置有各自类型。当前识别器没有真实验证码solver、协议或年龄执行器绑定；具体验证插件需提供当次公共内容指纹和可信授权回调。没有精确证据提供器时使用单次nonce，防止旧许可跨页面复用，不能据此直接执行恢复。

已具备安全的非绑定Bing cookie拒绝操作（一次点击后读回，不点泛化Accept/Next），以及账号限制/地区不一致/迟到账/弹窗/异常中断等测试。剩余完整业务与现场处理器保持pending，见能力对照表。

## 第四轮：punchcard、APP 与目标设置

--mode punchcards 只处理原私有部署允许的 WW_pcparent_redesign_existinguser_onboarding_offer_punchcard。保持 search/day/streak 子项延期、奖励领取默认关闭；native-config.json 的 punchcards.autoClaim=true 才请求这些子奖励。资格来自新鲜 quest 数据；缺失字段保持 unknown。不能拿上游 FlyoutDashboard 人工创建的空 punchCards 数组当成「无任务」。

server_actions.cjs 逐个读取当前页面引用的 chunk，最多60个、总12MiB；每个响应最多2MiB，发现冲突action ID即退出。提交沿用已审查的 Next server-action 协议，POST不自动重试。punchcard-journal.json 在提交前持久记录，跨进程再次执行只读核验，不能盲目重发。当前未暴露重置journal开关，需人工确认真实状态后再设计恢复。

APP 的 app.cjs 是实际HTTP绑定与 caller API：createClient 接收调用方提供的现有有效token/country/language，不创建token、不做OAuth、不写凭据、不自动加载环境凭据。runPromotions 保留 type=sapphire 的已知任务、最多40项、逐项三次读回；只有确切活动complete才完成。submitDaily 发送原type103并读回，但原响应没有独立签到完成字段，故目前标unknown，不能用余额增加冒充归因证据。ReadToEarn 已保留原type101与最多10次顺序调度、缺资格/停滞/不确定写入停止，只有特定offer完成才报告complete；该offer的实际现场数据形态仍待验证。APP没有自动读取凭据的CLI；full 的可信调用方可以通过 host.appClient 接入现有token客户端，普通JSON不能配置该回调。

goal.cjs 恢复原手动目标浏览器操作，准确SKU URL、明确手动兑换radio、Next/Okay、刷新读回；不下兑换订单，不选auto-redeem。extra 的 native-config.json.goal.url 可以指定既有目标URL，缺少可信授权回调时生成该目标的待处理checkpoint。调用方 setManualGoal 需传入经认证授权器验证的checkpoint、authorize回调、journal；配置JSON自身不能批准执行。已有目标不会切换其现有兑换设置。目标设置成功后 extra 还必须核验对应卡片完成。

初始总预算继承旧部署：Rewards7500秒（各mode相同），显式 --timeout 可覆盖；重试和阶段共用单次总预算，不重置计时。上述增加均仅通过离线假页面/传输测试，未运行真实账号或平台操作。


## 原生 full 编排与显式任务范围

每账号 state 目录必须提供 capabilities.json，例如：

```json
{"schema_version": 1, "enabled": ["daily", "desktop_search"]}
```

这里只是明确请求两项能力的例子，不代表原账号真实启用配置。根据自己的旧任务范围填写；缺失清单返回 capability_manifest_required，未知/重复名称、空列表或额外字段拒绝。完整名称见 full.cjs 的 ORDER：daily、extra、punchcards、desktop_search、mobile_search、bonus_search、more_promotions、claim、search_perk、streak_protection、app_daily、app_promotions、read_to_earn、visual_search，以及三个原实验能力。未接入的请求能力会列入报告并返回unknown，不偷偷忽略，也不启用未列出的可选任务。

full先只读快照，按固定顺序执行请求阶段，再只读快照；最多一个浏览器/上下文，阶段结束关闭。成功阶段的会话轮换仅在进程内按desktop/mobile分别传递，失败不替换有效副本、不新写凭据。全部阶段/重试共用runner总超时。初始快照或阶段的timeout/busy、账号限制、认证或需要授权的阻碍，都会停止后续动作；desktop会话缺失在任何APP调用前失败。

业务结果以请求能力为单位；本次run的 rewards-report.json 保存阶段明细（最多64KiB、每阶段原子覆盖、无网页/凭据）。快照只是观察，不能覆盖动作失败；已确认结果、unknown、partial、blocked与缺失绑定分别保留。full_requested_capabilities_complete只表示清单内能力确认完成，不意味着所有官方能力都已开发或验收。

可信host可在进程内调用createBindings({...,host})：host.appClient为当前账号已有APP客户端工厂；host.businessDate为明确业务日；host.goalCheckpoint/authorizeGoal提供经认证、精确范围校验的目标恢复接口。没有从JSON加载代码/授权，也不自动OAuth。CLI尚无聊天授权桥；checkpoint由可信宿主验证并重新探测后才能进入相应恢复入口。验证码、条款、年龄真实处理器及剩余业务继续按矩阵pending。
