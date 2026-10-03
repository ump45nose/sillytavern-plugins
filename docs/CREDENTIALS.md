# 按需读取凭据

所有凭据和浏览器账号状态在仓库外，权限 0600；平台入口仅向子进程传入自身声明的环境变量。公共运行器不扫描青龙数据库或其他账号。Hermes 可注入变量或私有配置路径，但凭据同步不是调度任务。

## CookieCloud

复用已有 CookieCloud 服务。`COOKIECLOUD_CONFIG` 指向私有 JSON：

```json
{"url":"http://your-existing-cookiecloud:18088","uuid":"your-private-uuid","password":"your-private-password"}
```

可选 `proxy`；内网服务默认直接访问。Aliyun 读取 developer.aliyun.com 的 Cookie，Laowang 读取 laowang.vip 的 Cookie。只返回目标站点可用 Cookie；过期数据不使用，缺失必需字段返回失败。每次请求限时 30 秒，响应最多 4 MiB，拒绝重定向，没有新服务或本地全站凭据缓存。

该可选路径需要 cryptography，在 HTTP venv 中安装：

```sh
.venv-http/bin/pip install --require-hashes -r locks/cookiecloud-python312-linux-x86_64.txt
```

支持现有 aes-128-cbc-fixed 和旧 OpenSSL Salted__ 格式；crypto 仅在读取时加载。Laowang Node 脚本用 `--python` 指定该环境进行一次性解密，目标 Cookie 只在私有进程间传递，不写 stdout 日报或日志。

## 其他平台

SMZDM/V2EX 使用各自 README 的 Cookie 变量。Rewards 使用私有 storage-state，必要时由已有会话获取 APP token。Epic 使用私有配置及账号 profile。没有把凭据统一放进共享数据库，也不新增凭据服务。
