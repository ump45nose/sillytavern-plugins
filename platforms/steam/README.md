# Steam：ASF / FreePackages 一次性执行器

已实现可运行的链路：PICS 变化发现 → package/app 核验 → Steam 官方商店永久赠送证据 → 已拥有核对 → 写入提交意图 → 请求免费 package → 到账读回 → common JSON 结果。只用 Python 标准库，不启动浏览器、不保存 Steam 密码、不创建 cron。

2026-10-07 已完成真实登录、持久重启恢复、只读发现和通知验收。用户随后授权免费领取，实际取得 Arena of Trophies 的免费许可，owned 回查与防重复检查通过；NAS 定时入口已开启 `--claim`。该验收样本使用单 app 的免费许可接口，自动限免发现仍保留以下普通游戏、活动期限和官方永久赠送证据规则，见 [部署记录](../../docs/STEAM_DEPLOYMENT_2026-10-07.md)。发现覆盖有限，证据不足的包继续待核查。

## 先跑模拟流程（无需账号、完全离线）

在仓库根目录：

```sh
python3 -m unittest discover -s tests -p 'test_steam*.py' -v
```

包括真实 `run.py` 启动器、子进程监督、账号锁、自动发现、HTTP IPC、免费领取 POST、owned 读回、原子 result/latest 文件的完整模拟。测试用的临时解释器将商店 HTTP 映射到 loopback fixture；生产代码没有商店地址覆盖开关。还覆盖不确定提交跨重启不重发、活动过期后只读恢复、登录失效、限流、无候选 no-op、Demo/Beta/DLC 排除等。

只检查生产入口，不访问任何网站：

```sh
python3 platforms/steam/run.py --runtime-root /absolute/private/benefits-data
```

返回 `execution_not_requested`（退出码 1）是预期行为。

## 真实环境前提与配置

1. 已由用户自行配置、登录并允许使用的 ASF 实例；IPC 已开启。账号实际国家必须与配置 `region` 一致，不能借 cc 参数绕区。
2. 已安装 Citrinate/FreePackages 插件。**保持每个 bot 的 `EnableFreePackages: false`**，禁用其他自动领取器；本适配器不启用后台泛收集、不调用 QueueLicenses。插件的只读与单 package IPC 不要求后台队列启用。
3. IPC 只通过 loopback HTTP 或可信 HTTPS；证书校验保持开启，禁止 URL 账号密码、查询参数及重定向。IPC 密码属于已有权限，本代码不会创建新凭据。
4. 同一主机的所有调用共享一个绝对 runtime-root。不同主机、独立 ASF/人工客户端的提交不受此本地锁/限流协调，避免并行使用它们。

将 `config.example.json` 复制到源码外的私有目录，填入现有 IPC 密码、单个 bot 名、精确 SteamID64 字符串及真实账号国家；文件仅自己可读：

```sh
chmod 600 /absolute/private/steam.json
export STEAM_CONFIG=/absolute/private/steam.json
python3 platforms/steam/run.py --runtime-root /absolute/private/benefits-data --account steam1 --execute
```

`--execute` 默认仍是只读发现/核验，不发领取 POST；合格候选显示 `dry_run_eligible`，退出码 3。日志不打印配置、原始响应或 IPC 密码。凭据放 JSON，不放命令行。

公开商店请求可在私有配置中显式设置 `store_proxy_url`，例如
`http://127.0.0.1:7890`；只接受没有认证信息的本机 HTTP 代理，未设置时直连。
仅匿名官方商店 GET 使用该代理，保持真实账号 `cc`、TLS 校验和禁止重定向，
不发送 Steam Cookie 或 IPC 认证。传输错误及 500/502/503/504 最多重试一次，
每次超时 10 秒；429、403、重定向不重试。IPC 和领取 POST 始终不自动重试。
代理自身的 Steam 商店路由也需实际验证，单纯指定代理不代表请求已走代理出口。

只有额外显式加 `--claim` 才开启真实领取。执行前应先审核只读输出并取得账号操作授权：

```sh
python3 platforms/steam/run.py --runtime-root /absolute/private/benefits-data --account steam1 --execute --claim
```

bot 必须是一个精确名字；拒绝 ASF、逗号列表、路径/空白。`/Api/Bot/{bot}` 返回必须只有这个 bot，已登录且 SteamID 匹配。ASF/Steam 登录过期或身份不符立即停止，由用户在 ASF 中恢复会话；这里不会自动登录、处理 Steam Guard 或 CAPTCHA。

## 自动发现边界与安全门槛

首次从 `GetChangesSince/0` 读取服务当前可提供的近期 PICS 变化，先原子保存游标及工作队列，再检查最多 30 个 package（配置 1–50）。后续从已保存游标读取增量，队列轮转，旧候选不会永远被最新批次挤掉。合格及证据不足的候选保留重查，已确认领取的移出；dry-run不会吃掉候选。可在 `discovery.change_number` 提供初始已知基线，已有状态不允许悄悄改基线。发现状态在共享 SteamID 目录的 `.discovery.json`，队列上限 4000 条。新增变化超限时，有持久队列就先处理旧队列，不接纳新窗口、不推进游标；没有旧队列可处理时停止并要求审核窗口/容量。不静默丢候选，也不将未接纳窗口算作已扫描。PICS 历史通常约 12 小时，ASF 启动晚或上游 full-update 标记意味着不完整；仍有待扫描队列、延期窗口或 full-update 输出 `discovery_coverage_incomplete`，`business.discovery=unknown`，不能当成“全站没有限免”。

每个候选必须同时满足：

- 完整、ID 对应的 PICS metadata；`billingtype=0`（NoCost）、`licensetype=1`（SinglePurchase）、`status=0`（Available）；缺字段不按零处理
- 非 freeweekend，有明确且未过期的 `extended.expirytime`；`starttime` 若存在必须已开始
- package 内所有 app 的 `appinfo/appid` 与 ID 对应、`common.type=Game`，排除 Demo、Beta/Playtest、DLC、未知类型；package 最多 5 个 app。明确 isfreeapp、beta/demo、playtest 标记及未核实的前置拥有条件也否决；同时检查 app/package 的国家 denylist/allowlist，无法解析则 hold
- 以真实地区、英文界面读取官方 Steam 商店；同一 `game_area_purchase_game` 购买块同时出现明确的永久赠送说明，以及指向同一 package 的免费 license 操作
- 支持官方免费 license form 的 hidden subid 或明确 AddFreeLicense 调用；仅折扣、价格为零、NoCost、用户评论、新闻标题或拥有关系都不足以证明永久赠送
- 领取前再次检查会话、拥有和当前时间。Steam region 拒绝不能用换地区、代理或另一账号绕过

领取截止时间取 PICS epoch；不猜商店显示日期的时区。商店文案/DOM 变化、年龄门槛、region 页面缺购买块、缺 deadline、包内容变化或 metadata token 缺失，一律 hold。`GetOwnedPackages` 如果返回空拥有错误会按 unknown/失败处理，不猜成空库。该接口只能证明持有 package，不能单独证明它是永久许可；永久性来自领取前的官方促销与 PICS 证据。

发现过程中明确非 NoCost、已过期、freeweekend、beta/demo、非游戏或 isfreeapp 的条目会被排除。类型和免费游戏排除先于期限检查，因此明确不适用的包不会仅因缺 expirytime 长期占用队列；排除所需的 metadata 仍必须完整且 ID 对应。缺失 metadata 的候选保留 `blocked` 原因。有覆盖缺口或证据不全时返回退出码 3。有限窗口内没有候选且源响应正常时返回 `no_candidates`、claim=`not_applicable`，是正常 no-op，不是成功领到游戏。

## 状态、幂等与恢复

- 复用 common 账号锁、进程总超时、原子 JSON。另按精确 SteamID 加锁并共用 journal，防止两个账号代号绕过幂等和限流
- journal 在 `state/steam/_steam_ids/<SteamID>.json`；只存 packageID、attempt 时间、pending/confirmed、限流截止，不存凭据
- 先原子持久化并 fsync intent，再发一次 `RequestFreeSubLicense?subID=…`。不入异步队列，不盲重 POST
- 上游 HTTP 200/Success=true 不是入库成功；Steam EResult、PurchaseResultDetail 和 owned 读回都参与处理。已拥有不是新领取数量
- 超时/断网后只读恢复；owned 确认前保持 unknown。活动消失或过期后，仍优先恢复历史 pending。发现失败不抹掉已确认恢复结果
- 本地最多每 10 秒一次提交、滚动 90 分钟最多 25 次，跨运行保留；服务端限流触发 90 分钟冷却。不会等待到活动过期后再提交，也不会在本次调用自动重试
- 本地限制不包含 ASF 外部的使用量。401/403 单次即停，防止错误认证触发 ASF IP 封锁
- 200 个 journal 条目达到容量后停止新提交，提示审核；不自动删除 intent。若要清理，应先确认所有历史提交及账号状态，备份后由操作者处理，不能把删除 journal 当重试按钮
- common 总超时默认 180 秒；单请求 15 秒。已有部分结果保留，但整个批次没有处理完时不会标 complete

## 可选：受控候选 manifest

无自动发现覆盖的活动可以准备源码外、0600 权限的审核 manifest，然后在配置中用 `candidates_path` 替代 `discovery`。它不是自动发现的必需输入。完整字段参见 `candidates.py` 与 `tests/test_steam.py: candidate()`。

manifest 必须明确 package/app IDs、game 类型、四个排除标志、永久赠送、零价格与正常原价、币种、地区、带时区起止、三类证据 URL、审核时间（不超过 1 小时）。未知字段不推断。手填文件禁止 `official_store_free_to_keep` evidence method；该保留模式只能由运行中的官方页面验证器生成。

## 已核接口与来源

- 源码接口审阅基线：FreePackages `9c8be907681fbc67c7bd70589ba7fc4245340b50`（2026-10-06 读取）。2026-10-07 已在 NAS 核验 ASF 6.3.10.3 + FreePackages 1.7.1.1 的真实只读响应，见 [部署与验收记录](../../docs/STEAM_DEPLOYMENT_2026-10-07.md)。已拥有列表的零号基础条目接受后排除，不作为候选。
- [FreePackages README / IPC 清单](https://github.com/Citrinate/FreePackages)
- [FreePackagesController](https://github.com/Citrinate/FreePackages/blob/main/FreePackages/IPC/Api/FreePackagesController.cs)：GetChangesSince、GetProductInfo、GetOwnedPackages、RequestFreeSubLicense
- [ASF IPC](https://github.com/JustArchiNET/ArchiSteamFarm/wiki/IPC)：Authentication header
- [Steamworks 官方 Free to Keep](https://partner.steamgames.com/doc/marketing/discounts/freetokeep)：专用 package 与永久持有语义
- [SteamKit 枚举](https://github.com/SteamRE/SteamKit/blob/master/Resources/SteamLanguage/enums.steamd) / [EResult](https://github.com/SteamRE/SteamKit/blob/master/Resources/SteamLanguage/eresult.steamd)
- [历史商店购买块结构](https://github.com/moonstar-x/free-games-crawler/blob/2322f553f182d94c9a0a5b718d65ef0db55c5bd8/test/crawlers/__mocks__/steam_page_game.txt)：仅核 DOM，不代表当前活动；测试重建最小结构，不包含原页面 sessionid

新代码没有复制上游实现或引入运行依赖。ASF/插件的版本升级可能改变协议；响应结构不符会停止领取。用户已授权免费领取，单个真实 F2P 游戏的官方免费证据、`RequestFreeAppLicense`、owned app/package 回查已验证；默认自动发现仍不批量收集 F2P。合格普通游戏的限时永久赠送正向分支仍需实际活动覆盖。
