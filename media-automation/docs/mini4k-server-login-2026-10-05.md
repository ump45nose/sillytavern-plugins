# Mini4K 服务端登录与 Relay 移除

共享包更新到 `0.3.3`，公共宿主为 `0.1.2`，MCP 后端为 `0.1.4`，查询网页为 `0.1.2`。
使用现有 MoviePilot、CloakBrowser `0.4.8`、Playwright `1.61.0` 和虚拟显示器，
没有新增登录页面、远程桌面、浏览器服务或数据库。

## 本次改动

- 删除 Mini4K Relay 实现、片单兼容导入、搜索／解析／健康检查回退及三个 Relay 配置项。
- 保留 `/config/filmwatchlist-mini4k-cloak-browser` 持久目录；镜像检索与主站资源获取分别复用各自域名的 Cookie，不跨域复制。
- 登录命令和业务请求共用 `.mini4k-session.lock` 文件锁，避免不同进程同时打开一个浏览器目录。
- 登录失效保留 `AUTH_REQUIRED` 和具体原因，Cloudflare 未完成保留 `CF_CHALLENGE`，解析失败原因传到现有下载警告。
- 请求策略默认保持 `quality`，MCP 参数说明明确只有用户要求均衡／控制体积时使用 `balanced`。之前《战狼》任务记录显式传入了 `balanced`，并非服务端默认降级。

## 首次登录与失效恢复

在 NAS 交互终端运行：

```sh
docker exec -it moviepilot /opt/venv/bin/python -m media_capabilities.acquisition.mini4k_login
```

终端输入账号，密码隐藏输入；交互命令不保存输入凭据，不接受命令行或环境变量密码。
默认以 root 执行的命令会先切换到已有会话目录的所有者，保持新会话文件与 API 运行用户一致。
命令访问主站 `/user/login`，使用已确认的 Drupal 登录表单。
登录后访问《战狼》的一个种子资源，关闭浏览器，再用保存的会话取得真实种子／磁力并解析 Hash。
命令返回 `OK` 才表示资源获取权限已经核实，不以 Cookie 存在或提交表单成功作为依据。
终端和用户桌面浏览器无需保持打开。

只读检查已保存会话：

```sh
docker exec moviepilot /opt/venv/bin/python -m media_capabilities.acquisition.mini4k_login --verify-only
```

自定义会话目录时添加 `--profile-dir`，其值必须与公共宿主的浏览器会话目录相同。
默认只读探针为 `mini4k:v2:mini4k.io:torrents:71690:-`；资源失效时可通过 `--candidate-id` 使用搜索返回的另一种子资源。
账号错误、登录验证码或 Cloudflare 无法完成时，命令返回非零状态和明确原因，不记录输入凭据，也不回退到外部浏览器。

本次用户补充要求由工具继续执行并将凭据保存在本地，凭据已保存于仓库外
`/home/yuwk/.config/media-automation/mini4k/secrets/login.json`，文件权限 `0600`、目录 `0700`。
自动登录工具读取该文件，经进程标准输入传入容器内现有登录函数；
不把账号密码放入命令参数、环境变量、MoviePilot 插件配置或执行日志。

## 验证与部署记录

基本离线冒烟通过：实际表单字段、跨进程会话锁、保存会话后重新核验、认证失败原因、异常不泄露密码、MCP `quality` 默认说明。
Mini4K 原有索引冒烟通过，构建 wheel 已检查不含已删除的 Relay 模块。

构建摘要、部署记录及协议结果保存在仓库忽略目录 `.build/mini4k-server-login-20261005`。
第一次切换后 MoviePilot 启动超过原 180 秒等待窗口，触发代码／配置回退；未回退业务数据库或 OAuth 状态。
现有容器启动脚本递归调整文件归属，涉及 Btrfs 写回等待，是本次启动缓慢的主要原因。
后续等待窗口延长为 600 秒；复用已经核对摘要的共享包安装目录，不重复开发或安装浏览器依赖。

正式部署已完成，备份位于
`/vol2/1000/Docker/moviepilot/config/backups/mini4k-server-login-20261005T041252Z`。
原有 9 条任务、7 个资源引用及 26 条片单记录保留，公共宿主与片单调度恢复原配置。
Mini4K 专用 Device ID、Tab ID、下载域名文件及片单兼容模块已从使用中的运行目录删除；
其他项目的 Relay 配置未改动。当前共享包加载路径为 `/config/media-capabilities-runtime/0.3.3`。
浏览器依赖仍为 CloakBrowser `0.4.8`、Playwright `1.61.0`，MCP SDK 仍为 `2.3.0`。

| 运行产物 | SHA256 |
|---|---|
| 最终共享包 wheel | `de2167ea0a070d4babcde46a03b77970614718c88f5abbbf2bc5355e88c177a0` |
| 最终 MCP 镜像 | `94f5ff7faeb78d8214e3562a2878fbebc5c98e84834fdab862f46cb40007e1d0` |
| 最终查询网页镜像 | `c68ba5334b64562138e5ab43d789166a76b5ab03ce9ca53e66069e80bd520d84` |

线上基本冒烟通过：匿名 MCP 请求返回 401，授权 initialize 和四个工具枚举正常，
公网 `policy` 参数展示 `quality` 默认值与明确的 `balanced` 使用条件；网页、网关健康及 OAuth 发现正常。
原 OAuth 状态和认证文件保留，没有调用下载工具。
登录前实际 API 检索《战狼》（2015，TMDB 335462）返回 20 个候选，
探针资源 `Wolf Warriors 2015.1080p BluRay x264-WiKi` 返回 `AUTH_REQUIRED`，
原因明确提示服务端会话缺失／失效并要求 NAS 登录，不再被 Relay 失败覆盖为 `UNAVAILABLE`。
业务 API 创建的会话锁为目录所有者 `1000:1001`，权限 `0600`；会话目录保留 `0700`。

用户首次运行登录命令返回通用的“登录／核验失败”，未返回 `OK`。
首次失败时只读工具检查确认登录与业务 API 使用同一目录，已保存 Cookie 只有 Cloudflare 类别；
`--verify-only` 返回 `AUTH_REQUIRED`。不提交表单的服务器探针能定位四个选择器，
且账号／密码字段均可完整写入测试字符串，没有使用账号凭据或提交登录请求。
登录命令已补充固定的操作阶段及异常类型提示（例如“提交登录表单超时”），
不会打印可能包含输入内容的原始浏览器异常。
原有认证、真实链接及 Hash 校验条件保持；验收结论只依据程序断言和工具执行结果。

工具随后捕获到资源页导航的 `net::ERR_ABORTED`。
已安装的 CloakBrowser 拟人点击直接调用鼠标操作，原来的加载状态等待可以在旧登录页上立即返回。
登录流程改为点击前订阅并等待提交后的导航，完成后才访问资源页，修复了这次登录失败。
相应基本冒烟验证了等待开始、提交点击、导航完成的顺序与安全的错误阶段提示。

**资源获取已恢复，重启后会话复用通过**：工具登录返回 `OK`，关闭并重新打开持久浏览器后取得真实种子；
再实际重启 MoviePilot 容器，核对启动时间及 PID 已变化，并重新取得相同种子。
程序断言确认磁力／种子 Hash、重启前后 Hash、文件清单及总大小一致；业务 API 的搜索和解析均返回 `OK`。
《战狼》搜索仍返回 20 个候选，核验候选为 `mini4k:v2:mini4k.io:torrents:71690:-`。
最终工具结果为 `PASS`，详见 `.build/mini4k-server-login-20261005/final-acceptance.json`。

- 资源：`Wolf Warriors 2015.1080p BluRay x264-WiKi`
- Hash：`cd26c3bba1b3262b0aa79e55750bc07cc8fd4ec6`
- 种子文件本身：`43,941` 字节；`private=false`
- 种子元数据总大小：`8,977,853,080` 字节，共 5 个文件。

| 种子内文件 | 字节数 |
|---|---:|
| `Wolf.Warriors.2015.1080p.BluRay.x264-WiKi.mkv` | 8,872,595,071 |
| `Sample/Wolf.Warriors.2015.1080p.BluRay.x264-WiKi.Sample.mkv` | 105,253,080 |
| `Wolf.Warriors.2015.1080p.BluRay.x264-WiKi.nfo` | 4,771 |
| `村口老蔡.txt` | 80 |
| `Wolf.Warriors.2015.1080p.BluRay.x264-WiKi.md5` | 78 |

重启验收前备份为
`/vol2/1000/Docker/moviepilot/config/backups/mini4k-session-restart-20261005T061103Z`。
本次重启前后 10 条任务、7 个资源引用和 26 条片单记录均保留，原插件配置与调度已恢复。
最终三个运行副本的登录模块摘要一致，现有浏览器依赖、OAuth 配置和业务 API 参数保持。

上述登录与重启验收没有提交真实媒体下载。随后用户明确要求验证实际下载链路，结果如下。

## 115 实际下载验收

当前配置 `p115_route_enabled=true`，Mini4K 公开 BT 默认提交到已有 P115StrmHelper 的 115 离线下载；
电影目录为 `/Media/Movie`，剧集目录为 `/Media/TV_Show`。公开 BT 下载与 115 分享开关分别控制。
聚合检索同时包含 M-Team；自动选中的 PT 资源仍使用 MoviePilot 下载器。

工具实际执行公网 MCP `search_resources → download_media → get_download_status`，
明确指定上述《战狼》Mini4K 候选，再读取 115 原生任务与云端文件。
任务为 `mini4k-115-e2e-20261005-cd26c3bb-02`；程序断言结果为 `PASS`：

- MCP 最终回执为 `completed`，进度 `100%`，路由 `public_bt`。
- 115 原生任务为 `status=2`、进度 `100%`，Hash 为 `cd26c3bba1b3262b0aa79e55750bc07cc8fd4ec6`。
- 云端目录为 `/Media/Movie/Wolf.Warriors.2015.1080p.BluRay.x264-WiKi`。
- 实际 5 个文件、各文件大小及总大小 `8,977,853,080` 字节与种子元数据完全一致；下载目录父级一致。
- 持久任务记录已更新为完成，该 Hash 仅登记一个下载任务。
- 请求未传策略；默认仍为 `quality`，明确指定候选后的实际策略显示为 `manual`。

首次 MCP 调用在解析阶段返回 `UNAVAILABLE；资源页访问失败`，回执为 `no_match`，没有提交到下载器或登记提交意图。
工具随后解析同一候选成功，确认无提交记录后使用新的请求 ID，实际创建一个 115 下载任务。
115 首次状态曾为失败、进度 `0%`，后续同一任务的原生接口和 MCP 均返回完成、进度 `100%`；没有重复提交。
115 当时有 683 条离线任务、23 页，全量查重因分页间隔约需 44 秒。
本次未改业务代码，首次解析失败的具体原因尚未定位；保留该失败回执，不将重试成功视为已修复偶发解析失败。

全部判定来自工具执行结果与程序断言，没有使用模型判断覆盖校验条件。
原始回执、云端核验与汇总位于仓库忽略目录 `.build/mini4k-115-e2e-20261005`，
汇总文件为 `final-acceptance.json`。验证范围到 115 云端下载完成，STRM／媒体库入库未验证。

## 回滚

部署前备份位于 NAS 私有配置目录的 `backups/mini4k-server-login-*`，权限受限。
备份保存本次代码／Compose、原插件配置及 Mini4K 专用凭据副本；不会改动其他项目的 Relay。
恢复运行副本前暂停新提交，仅恢复本次代码、镜像和配置，不使用旧数据库覆盖后续业务记录，也不恢复旧 OAuth 状态。
