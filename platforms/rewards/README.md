# Microsoft Rewards

按启用清单顺序执行一次账号任务，阶段之间关闭浏览器，最后输出通用 JSON 和本次 `rewards-report.json`。Hermes 决定何时运行、如何汇总和推送。统一结果补充进度、余额变化、锁定数量和未确认任务明细，见 [结果契约](../../docs/RESULTS.md)；不把余额差当全天积分收入。

## 安装和账号状态

Python 3.12、Node 24、patchright 1.61.1 和原生 Chromium。保留 sandbox，不导入上游 Main 或其通知/数据库/账号扫描代码。

```sh
cd platforms/rewards
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
npx patchright install chromium
```

在仓库外的 `state/rewards/<account>/` 准备 `storage-state.json` 和 `capabilities.json`。当前迁移保留旧部署启用的八项：

```json
{"schema_version":1,"enabled":["daily","extra","punchcards","desktop_search","more_promotions","claim","app_daily","app_promotions"]}
```

可选 `native-config.json` 保存已有稳定地区/设备和搜索配置，例如：

```json
{"region":"US","language":"en-US","search":{"maxSearches":100,"stagnantLimit":3,"delayMs":30000}}
```

请用账号实际地区；不根据示例改变地区。凭据文件不进 Git。

```sh
REWARDS_ROOT=/absolute/project/platforms/rewards \
REWARDS_PROXY=http://your-existing-proxy:7890 \
python3 platforms/rewards/run.py --runtime-root /absolute/private/runtime \
  --execute --browser-cache /absolute/browser-cache
```

## 能力与确认

- `daily`：逐个执行当前每日活动卡片，重新读进度到上限。
- `extra`：社交、已配置目标和探索必应。探索先用当前任务 hash 激活，再用对应主题搜索，以该任务自身的完成/积分读回确认。锁定任务保留 blocked。
- `desktop_search`：读取当前账号桌面额度，未满时搜索、等待入账，达到额度或连续停滞则退出；已满不重复搜索。
- `punchcards`：旧部署白名单 onboarding 任务；完整清单没有分配该任务时不适用。不会把其他任务组冒充同一任务。
- `more_promotions`：当前可执行 URL 活动，当前 action ID 和任务 hash 绑定，发出前记录 intent。
- `claim`：明确有待收积分时提交一次；无待收积分不适用。
- `app_daily` / `app_promotions`：通过已有浏览器登录进行 OAuth，token 存在私有账号目录；随后一次性 HTTP 客户端执行 APP 任务，不保留后台浏览器。APP 签到优先用当前页面进度确认，不能把 1000 分连续签到奖励误认作每日签到。

2026-10-03 实测每日活动、桌面搜索、APP 签到与 APP 活动确认；无分配的 onboarding 和无待收积分均不适用。更多活动有平台锁定项；探索必应仍按 [验收记录](../../docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md) 报告，不用部分成功代表全部完成。

## 独立模式与边界

`--mode activities / snapshot / extra / desktop-search / mobile-search / punchcards` 可单独调用。snapshot 只读，结果按 mode 保存，避免覆盖 full 日报事实。

移动搜索需要自己的 `storage-state.mobile.json`，以及 `native-config.json` 中 `mobile.isMobile=true` 和稳定 userAgent；不拿桌面会话冒充移动设备。read_to_earn 有独立 APP 组件，但不是当前旧部署启用项。Edge 时长、视觉搜索、实验 API 搜索等未绑定的请求会明确保持未完成，不静默跳过。

登录失效、验证码、地区不一致、账号限制等会返回明确原因。新增兑换目标需真实目标 URL 和对应操作授权；没有默认目标、自动兑换或伪造年龄数据。

HTML 最多 2 MiB，flyout 最多 4 MiB，账号状态最多 1 MiB。有限活动、查询、轮询和总时限共同限制运行；结果不保存网页/截图/完整 API 响应。实际浏览器内存不是硬限额。

解析器仅加载 `vendor/rewards-parser/` 中固定的约 26 KiB JS，无运行时依赖；不安装完整上游应用。协议适配参考 TheNetsky/Microsoft-Rewards-Script v4.3.2，GPL-3.0-or-later；来源、编译证明和完整许可证保留。历史能力对照见 [REWARDS_PARITY](../../docs/REWARDS_PARITY.md)。
