# Epic 能力与自动化障碍对照

本次重写目标是降低常驻和峰值内存，不以删除合理业务或恢复能力换取“轻量”。本表依据 Ronchy2000/epic-freebies-helper 的已固定 d90190b 源码及原 epic-freebies-verifier 覆盖层；源码定位保留原函数名便于复查。不是线上行为验收，表中“保留”表示目标要求，不代表已实现。

## 分类与取舍

| 编号 | 原实现定位 | 实际问题 | 重写取舍与回归要求 |
|---|---|---|---|
| E01 | EpicAuthorization.invoke / _get_login_status / _has_account_session | 导航登录标记延迟或缺失，已有会话仍有效 | 保留站点标记和账号端只读探测双证据；缺失标记不能立即密码重登。测试标记缺失、订单接口可用、两者冲突 |
| E02 | login_compat.ensure_store_session / wait_form | 账号域已登录但商店 SSO 未完成；Welcome back、Done linking | 保留识别与恢复；确认当前账号，限制跳转目标。账号关联具有单独授权边界；无条件点击 Done linking 改为有上下文的动作 |
| E03 | EpicAuthorization._wait_for_login_form | 预登录安全页使表单不出现 | 保留检测、等待、可见挑战处理；移除自动 clear_cookies，因为会破坏仍有效会话。使用原覆盖层“不清会话”的改进 |
| E04 | login_compat.click_gate / _submit_login_or_accept_challenge | Cloudflare 可见验证挡住按钮 | 保留可见挑战识别与按需处理能力；使用可验证的控件定位优先于固定坐标。执行前有对应授权，超时后只读确认，不重复盲点 |
| E05 | _has_visible_hcaptcha / _await_login_outcome / extensions.hcaptcha_runtime | 隐藏 iframe 不等于活跃挑战，挑战可能延迟出现 | 保留可见性判断、延迟探测、求解结果观察；求解插件按需加载并及时卸载相关进程。超时和失败不得当成登录成功 |
| E06 | hcaptcha_adapter / numbered_line_solver / llm_adapter | 拖拽、编号连线等具体挑战及模型兼容 | 保留为可选按需能力插件，按原分支建立离线图像/交互夹具。未完成插件接线时明确待实现，不标为故意不支持 |
| E07 | _login / _resubmit_password_form / _on_response_anything | 会话过期、登录提交无结果、响应信号缺失 | 保留认证恢复入口，先已有态、再受控登录。密码通过安全输入/凭据渠道，不进入日志。有限重试以当前状态为依据，不仅靠 analytics 响应 |
| E08 | epic_totp_service / _await_login_outcome | MFA、过期 TOTP、验证码之后代码失效 | 保留 MFA 处理、时钟/代码窗口、失败上限和等待冷却。验证码完成后先观察是否已通过，再决定新 OTP；移除“建议关闭 2FA”的指导 |
| E09 | _dismiss_mfa_setup_prompt / _handle_right_account_validation | 登录后的安全设置、确认本人或提醒弹窗 | 保留识别与状态分类；纯提醒可按既定授权处理，改变安全设置不能自动推断许可。不通过一组 #yes/skip 盲点所有弹窗 |
| E10 | _needs_privacy_policy_correction / _agree_license / _uk_confirm_order | 隐私页面、新条款、区域专用结算确认 | 保留识别、提取具体说明、等待必要批准、继续和结果读回；禁止用永久“全部同意”标志覆盖未来新文本 |
| E11 | add_promotion_to_cart 的 Continue 分支 | 年龄限制弹窗 | 保留自动填充/提交接口，但仅使用用户提供的真实数据与对应许可；不猜生日、不默认成年，不将任意 Continue 当年龄确认 |
| E12 | _goto_claim_page / _goto_product_page | 页面超时但关键 DOM 已加载 | 保留有界导航重试及停止未完成加载；必须有业务 DOM 证据才继续，不只凭 URL 字符串判成功 |
| E13 | _replace_page / 页面异常清理 | 页面损坏、上下文状态异常 | 保留单页重建，不默认清全部 Cookie/profile；关闭事件监听和旧页面，不让失败页面累计 |
| E14 | browser_context backend / proxy / launch options | Camoufox 不可用、浏览器版本/profile 不兼容、代理路径不同 | 保留明确的依赖诊断和可配置后备；各后端独立 profile，切换需验证会话。不得静默覆盖旧 profile。按需 Xvfb，取消默认全程录屏 |
| E15 | get_promotions / PromotionGame / collection summary | 免费活动、bundle 与普通商品 URL、重复活动 | 保留库存解析、精确商品身份、时间和免费资格校验、去重。未知/缺失接口不可当“本周无游戏” |
| E16 | add_promotion_to_cart / _log_purchase_button_context | 商品不存在、已拥有、不可用、即将上线、按钮禁用 | 保留状态区分；移除“disabled/Unavailable/Coming soon 就当已拥有”的宽泛结论。已拥有必须由精确库状态或可信订单确认 |
| E17 | _click_purchase_button / _has_purchase_progress | 普通点击超时、遮罩、checkout iframe 已打开 | 保留观察已有进展再恢复。避免 standard/dom/force/坐标多次动作叠加；同一提交最多一次，不确定则先核验 |
| E18 | _handle_device_not_supported_modal / _click_visible_continue_button | 商店误报设备不支持或出现额外提示 | 保留特定提示检测与已知安全恢复；不为消除报错执行页面内任意按钮点击。弹窗含条款或安全选择时转对应处理 |
| E19 | _ordered_checkout_containers / _active_purchase_container / _wait_for_checkout_ready | 结算可能在 page/frame/iframe，重渲染和 overlay 延迟 | 保留多容器识别和短有界等待，重新定位而不复用过期 locator；不退化成遍历点击所有按钮 |
| E20 | claim_guard.zero_total / _submit_place_order | 结算金额与促销 API 不一致、未知货币布局 | 保留结算时明确零金额、单次下单、区域格式验证。冲突多个 Total、负数、无法解析均停止；不能依赖 API 免费就支付 |
| E21 | claim_guard.preserve_cart / upstream _empty_cart | 用户购物车已有付费商品 | 保留“读出并保护”，删除上游自动移动付费商品到愿望单的行为。读取失败不等于空购物车；不清空用户数据 |
| E22 | _handle_instant_checkout / _purchase_free_game | 直接领取与购物车领取两条流程 | 两条都保留；分开建状态机和用例，不只实现一种按钮布局 |
| E23 | _resolve_checkout_security_check / _probe_checkout_challenge / _extended_checkout_challenge_probe | 下单阶段可见或延迟出现的挑战 | 保留挑战处理与有界复查，和登录阶段共用插件但不共用错误状态；不得绕过支付金额/条款检查重新提交 |
| E24 | _raise_if_free_game_rate_limited / _claim_state_reason | 免费游戏次数限制、账户受限、设备提示 | 保留原因分类与冷却，禁止把限流当网络抖动高频重试；下次执行先读回，不无限自愈 |
| E25 | _is_promotion_in_order_history / _confirm_promotion_claimed / run.py storefront fallback | 订单延迟、非 JSON 安全门、按钮暂时禁用 | 保留订单与商品页双重只读确认。非 JSON 不直接判未登录；仅精确 In Library 等已验证状态可确认拥有 |
| E26 | _finalize_unconfirmed_checkout / collect_weekly_games / CollectionSummary | 一部分领取成功、另一部分不明确；重试可能重复下单 | 保留按商品结果与最终 reconcile。重跑只处理仍未确认且可安全执行的商品；不因总任务非零而重放全部 |
| E27 | _capture_purchase_debug / redact_totp_inputs / redact | 故障诊断需要证据但可能含私密数据 | 保留脱敏、失败截图和必要计数；大小/数量有界、原始响应不进 Telegram。修复 GEMINI/GLM 配置脱敏不一致 |
| E28 | worker / GNU timeout / browser_context finally | 任务中断、浏览器/Xvfb/子进程遗留 | 保留总时限、关闭 context、进程组回收与不可保证的脱离进程边界。去掉常驻 worker，不删除合理清理逻辑 |
| E29 | telegram/wxpush 通知服务 | 自动化执行后需要可知状态 | 保留结构化可汇总结果，由 Hermes 通知；不重复启动另一套通知服务或继承不相关通知凭据 |

## 原生重写的模块边界

- session：现有 profile/账号状态、SSO、认证恢复、MFA；不常驻浏览器
- obstacles：识别上述页面状态，触发合适恢复或等待具体授权，不直接把所有异常降为失败
- challenges：按需插件，支持原项目合理题型/模型适配，加载只发生在真的遇到挑战时
- promotions：只读活动库存、商品身份与资格
- checkout：购物车保护、明确零金额、直接领取/购物车分支、单次副作用
- verification：订单/库状态/延迟确认和部分结果
- run：一次调用、逐商品执行、共享账号锁及全局浏览器锁、明确总预算

共用 common/interventions.py 只处理请求身份、范围与过期验证。它不是认证服务：随机写一个 approval.json 不代表用户批准。外部调用方必须验证真实授权。恢复先重新读当前页面/订单，再验证请求是否仍匹配；已完成就记账，不重复执行。年龄数据与机密凭据不放 checkpoint。

## 交付门槛

每个编号必须有具体回归用例和实现状态；可以标“待实现/待实测”，不能靠改成 human_required 或删除入口伪称能力保留。默认自动化在缺少所需授权时暂停，但接到合法授权后须有继续执行路径。仅能识别而不能恢复的分支要明确标明。

现阶段 claim 默认入口仍保持阻塞。尚无真实浏览器/网站验收；下一阶段按此矩阵实现并测试，不将表格本身当成功能完成。

## 2026-10-01 补充验证

- E05/E23：可见性检测遍历最多 32 个候选控件，避免第一个隐藏的验证 iframe 遮住后续可见挑战。候选过多明确暂停，不截断后假定页面已就绪
- E25/E26：新增有界只读入库确认，默认最多 3 次、间隔 2 秒且服从任务总时限；历史不确定提交也先读回。读取超时可重试，提交不会重放。下单后遇到挑战时仍在结果中保留该商品的“不确定”状态
- 云端浏览器公开页检查：Epic 免费游戏页显示“再进行一步操作 / 请完成安全检查以继续”；一次刷新后仍停留在安全检查。没有尝试解题、登录或领取，没有取得真实商品页/购物车/结算 DOM。该中文标记已加入挑战检测离线回归，不能据此宣称挑战已解决
- 上述新增回归使用合成 driver/页面对象；Epic 专项共 58 项通过。真实页面结算身份和金额绑定、认证恢复及各题型插件仍待接线和实测
- 执行环境重建后，从精确 Git 检查点恢复源文件，再重建本节所述改动，58 项 Epic 回归重新通过；不把此前中断的总体验证当作通过

## 已知表单的恢复绑定（离线）

`gates.py` 增加 E02 的精确 remembered-account 与 Done linking 处理器，以及 E10 原 `label[for=agree]` / `#agree` / Accept 表单处理器。来源是上述固定 commit 的登录覆盖层和 `_agree_license`，没有遍历点击任意 Continue。账号选择只允许调用方明确提供的账号；remembered-account 归为 login 授权步骤。条款处理器要求可信调用方确认当前披露内容指纹及协议链接一致，复选框使用幂等 check；隐私 correction 表单不冒充同一流程。每次处理后仍须重新观察站点，点击返回不当作成功。

11 个新增假页面测试覆盖精确账号、关联、表单歧义、目标域、条款变化、缺失链接、禁用按钮和隐私分支。Epic 专项 69 项通过。它们是具体 UI 处理器，不是完整登录/条款集成：真实站点布局、隐私表单、MFA、年龄输入、可信授权与接受后通知渠道尚未接通；公共 claim 仍未启用。

原生入口的未完成原因现为 `native_browser_and_approval_bindings_pending`；不再要求部署旧 Epic 应用才能检查新入口。compat.py 与来源 hash 仍用于离线审计。增加入口回归后 Epic 专项 70 项通过。
