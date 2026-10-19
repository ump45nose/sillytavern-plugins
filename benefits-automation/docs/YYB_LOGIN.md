# 共用 YYB 微信登录能力

影视飓风和 Olé 的执行器共用一个 YYB 取码服务。Hermes 继续调度平台任务，商家登录、签到和积分查询留在各自平台适配器内。

## 客户端接口

```js
const {getCode} = require("../../common/wechat_code.cjs");
const code = await getCode(privateConfig.wechat, miniAppId);
// code 仅在内存中交给本平台的商家登录请求。
```

调用方已读取的 `privateConfig.wechat` 只包含三个字符串字段：

```json
{
  "url": "http://127.0.0.1:33082",
  "token": "<与服务端 YYB_PROTOCOL_TOKEN 一致的私有值>",
  "account": "<YYB 账号数字 ID 或其 OpenID>"
}
```

`url` 是服务根地址，可包含反向代理路径前缀；不包含用户名、密码、查询参数或片段。客户端使用 Node 内置 HTTP/HTTPS 直连此地址，不继承出站代理。若执行器在容器内运行，应填它实际可访问的 YYB 地址，不能把宿主回环地址当成容器回环地址。

请求为 `POST /wxapp/getCode`、`Authorization: Bearer <token>`，JSON 为 `{ref: account, app_id: miniAppId}`。返回值只是一条非空 code 字符串，不带账号资料。当前接口要求账号引用为字符串；例如数字 ID 写成 `"1"`。

固定版本的成功响应结构为：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "openid": "<YYB 账号身份>",
    "account": {"id": 1},
    "result": {"code": "<一次性登录凭证>", "errMsg": "login:ok"}
  }
}
```

客户端检查 HTTP 200、外层 `code === 0`、内层 `errMsg === "login:ok"` 和非空 code；不会将外层业务码或旧服务的 `data.code` 当作登录凭证。完整请求限时 30 秒，响应最多 64 KiB，不跟随重定向、不自动重试。

影视飓风使用 AppID `wx92782ef90ebc836d`，Olé 使用 `wx6c61aaeba1551439`。它们的商家会话由平台执行器分别缓存；只有确证商家登录失效时，才获取新 code 并登录。一次 code 不能同时登录两个商家，也不能缓存供下一天复用。

## 稳定错误与日报接入

所有拒绝均为普通 `Error`，`error.message` 仅包含下列固定原因，不包含配置、账号、响应正文或底层网络错误文本。调用方直接将原因映射到平台结果；集成日报可按共用服务原因合并受影响平台。

| error.message | 含义 |
| --- | --- |
| `wechat_code_configuration_invalid` | 地址、协议令牌、账号引用或 AppID 未配置正确；请求未发出 |
| `wechat_code_authentication_invalid` | 服务返回 401/403，需核对协议令牌或服务访问权限 |
| `wechat_code_account_unavailable` | 服务返回 409，需检查 YYB 账号状态或重新扫码 |
| `wechat_code_service_unavailable` | 其他非 200 状态；包括账号不存在、路径错误或上游协议调用失败，不能仅据此断言微信凭据过期 |
| `wechat_code_redirect_rejected` | 服务返回重定向；客户端未向 Location 发送凭据 |
| `wechat_code_response_invalid` | JSON/成功结构/code 不符合已核对协议 |
| `wechat_code_response_too_large` | 响应超过 64 KiB |
| `wechat_code_timeout` | 完整调用超过 30 秒，包括持续缓慢输出正文的情况 |
| `wechat_code_connection_failed` | DNS、TCP、TLS 或响应流中断 |

YYB 自身可能在一次取码调用中恢复它的微信协议会话；客户端不会再叠加重试。平台的签到提交是否可以恢复，仍须由商家只读状态确认。

## 已固定来源与镜像

| 项目 | 已核对值 |
| --- | --- |
| 上游 | [525815266/YYB-Go-Enhanced](https://github.com/525815266/YYB-Go-Enhanced) |
| 版本 / 提交 | v0.2.33 / `fe1cf72495498a6a7c0ddcce4c80d93fc163788a` |
| linux/amd64 镜像 | `ghcr.io/525815266/yyb-go-enhanced:0.2.33@sha256:0fe1fba25f08b9d00c4276bed3226f95117d7e4ac40b6e96fd061b1548a16dd1` |
| 镜像版本与源码标签 | 已下载检查：version `0.2.33`、revision 与上述提交相同 |
| 原生运行身份 | `yyb`，UID 100 / GID 101；镜像大小约 40.2 MB |

协议依据为固定提交的 [接口说明](https://github.com/525815266/YYB-Go-Enhanced/blob/fe1cf72495498a6a7c0ddcce4c80d93fc163788a/docs/protocol-api.md)、[HTTP 路由及响应封装](https://github.com/525815266/YYB-Go-Enhanced/blob/fe1cf72495498a6a7c0ddcce4c80d93fc163788a/internal/httpapi/app.go)与 [GetCode 实现](https://github.com/525815266/YYB-Go-Enhanced/blob/fe1cf72495498a6a7c0ddcce4c80d93fc163788a/internal/protocol/pool.go)。客户端为本项目独立编写的协议调用代码，没有复制上游实现；上游参考源码保留在聚合 Git 之外。该提交未发现 LICENSE 文件，不将其完整源码并入本项目或标为本项目许可。

## NAS 待部署片段

本轮只准备方案。当前正式组为 `automation`，其入口是 `/vol2/1000/Docker/stacks/automation/compose.yaml`；沿用已有 `favsync_default` 网络。网页登录/微信协议均使用本服务自己的 SQLite，无需新增 PostgreSQL、Redis 或其他数据库服务。33082 回环端口在本次检查时可用，应用前仍需重查。

以下片段供集成到 automation 的 `services`；此文档不是另一个正式 Compose 入口：

```yaml
services:
  yyb:
    image: ghcr.io/525815266/yyb-go-enhanced:0.2.33@sha256:0fe1fba25f08b9d00c4276bed3226f95117d7e4ac40b6e96fd061b1548a16dd1
    container_name: benefits-yyb
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    command: [-host, 0.0.0.0, -port, "8000", -resource-root, /app/resource,
              -keepalive-interval, 1m, -keepalive-ahead, 45m]
    environment:
      TZ: Asia/Shanghai
    env_file:
      - path: /vol2/1000/Docker/stacks/automation/env/benefits-yyb.env
        format: raw
    volumes:
      - /vol2/1000/Docker/benefits-yyb/data/db:/app/resource/db
      - /vol2/1000/Docker/benefits-yyb/data/avatars:/app/resource/avatars
      - /vol2/1000/Docker/benefits-yyb/data/qr:/app/resource/qr
    ports:
      - 127.0.0.1:33082:8000
    networks: [favsync_default]
    labels:
      com.centurylinklabs.watchtower.enable: "false"
    healthcheck:
      test: [CMD, wget, -qO-, http://127.0.0.1:8000/health]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

私有 env 文件最小内容如下；实际密码与随机协议令牌由部署阶段在私有文件中生成，目录 0700、文件 0600：

```dotenv
YYB_AUTH_DRIVER=sqlite
YYB_ADMIN_USER=<自选管理员名>
YYB_ADMIN_PASSWORD=<私有强密码>
YYB_PROTOCOL_TOKEN=<私有随机协议令牌>
YYB_COOKIE_SECURE=false
```

保持面板连接凭据未配置，不启用青龙/呆呆/Arcadia 同步或任务创建；空连接凭据在已核对版本中使面板驱动处于未配置状态。首次网页登录后关闭不需要的公开注册。三个数据目录仅为本服务新建并授予镜像原生 UID 100/GID 101 读写，保留其他卷权限；用实际身份验证写入。更新保留整个 db 目录、账号、管理员及刷新凭据，不用删除数据库恢复登录。

宿主 Hermes 直接访问回环入口。首次扫码可从桌面 SSH 转发该回环端口后，在浏览器登录并扫码，无需新增公网监听。容器里只读检查 `/health` 证明服务存活，不能证明微信或商家登录有效。

正式应用时按 fn-service-ops：保存受影响配置、从 automation 入口校验、只更新 yyb 服务；同步 STACKS 与启动登记，再执行容器启动检查。回滚只撤回本服务定义/镜像，保留最新登录数据。本轮未进行这些生产操作。

## 分项验收

1. 客户端离线验证：`node --test tests/wechat-code.test.cjs`。使用本地 HTTP 模拟服务，覆盖认证、响应契约、大小、重定向、网络中断和完整 deadline。
2. 服务启动及鉴权：固定镜像临时运行，使用独立 tmpfs 数据、回环随机端口、原生非 root 身份、只读根文件系统；结束后删除容器。该步骤不包含真实微信账号。
3. 用户身份验证：网页登录，手机扫码添加 YYB 账号，确认已有目标小程序注册/授权；记录账号引用到私有配置。
4. 分别取影视飓风与 Olé code，在各平台执行器中当次换取商家会话。分别核对会员身份、签到状态和积分，不输出一次性 code。
5. 验证 YYB 凭据刷新、进程重启后持久恢复及两个商家会话失效后的重新登录。网络失败和服务认证错误应清晰报告，不误判为两个商家同时失效。

第 3–5 项需要真实用户身份和正式接入，本轮未验证。
