# Pixiv 收藏与 Wallabag EPUB

这两个来源由 Favsync 的同一个 8 小时任务调度。手动执行仍使用 `sync-once`，
`state/worker.lock` 防止它与常驻任务重叠。取消收藏、删除 Wallabag 条目或原站失效都不会删除本地文件。

## Pixiv

Pixiv 使用 gallery-dl 的官方 Pixiv 提取器。公开/私密插画收藏与公开/私密小说收藏分别启停，
首次启用会下载接口当前可见的全部收藏，之后完整遍历并按作品 ID 去重。插画、漫画和动图使用
提取器返回的作品类型，不按页数猜测。小说强制 `full-series=false`，只保存被收藏篇目；
`novel_embeds` 只控制正文插图。

先获取 OAuth refresh token。此命令会在终端显示敏感 token，不要把输出发到聊天或写入日志：

```bash
cd /home/yuwk/favsync
docker compose run --rm --entrypoint gallery-dl favsync oauth:pixiv
install -m 600 /dev/null secrets/pixiv-refresh-token
# 在本机编辑 secrets/pixiv-refresh-token，只放一行 refresh token。
```

然后编辑 `config.toml`：

```toml
[pixiv]
uid = "你的数字 UID"
refresh_token_file = "/run/favsync-secrets/pixiv-refresh-token"
picture_dir = "/downloads/Pixiv/picture"
novel_dir = "/downloads/Pixiv/noval"
ugoira_enabled = false
novel_embeds = true

[pixiv_art_public]
enabled = true
account = "personal"

[pixiv_art_private]
enabled = true
account = "personal"

[pixiv_novel_public]
enabled = true
account = "personal"

[pixiv_novel_private]
enabled = true
account = "personal"
```

`noval` 是本项目约定的实际目录名。小说 TXT 平铺保存，正文插图以页号后缀保存。
插画/漫画少于 8 页时在 `picture` 平铺；8 页及以上生成一个含全部页面与
`ComicInfo.xml` 的 ZIP，并在正式改名之前检查页数和 CRC。动图默认关闭；启用后保存到
`picture/ugoira`，首版不转换格式。文件名前缀是
`作者_系列名(如有)_标题_作品ID`，多页追加 `_p001` 等稳定页号。

前台首轮验收：

```bash
docker compose stop favsync
docker compose run --rm favsync --config /app/config.toml sync-once
docker compose run --rm favsync --config /app/config.toml status
find /vol3/1000/Picture/Downloads/Pixiv -maxdepth 2 -type f | sort
docker compose up -d favsync
```

至少分别新增一篇公开/私密插画或漫画和一篇公开/私密小说，再检查后续一轮能发现它们。
重复运行后文件数量应不变。当前仓库的自动冒烟只验证类型分流、可见性 URL、命名状态和 ZIP 逻辑；
没有 refresh token 时不能把这些测试表述为真实账号下载通过。
更换 Pixiv UID 时应使用新的本地 `account` 标签；沿用旧标签会报 `pixiv_account_changed`，防止混用状态。

## Wallabag 与 Wallabagger

Wallabag 使用官方 `wallabag/wallabag:2.6.14` 镜像和独立 SQLite，不连接 NAS 上其他业务数据库。
默认只监听配置的 NAS 局域网地址。启动服务：

```bash
cd /home/yuwk/favsync
docker compose --profile wallabag up -d wallabag
docker compose ps wallabag
```

当前 NAS 地址是 `http://192.168.31.201:18081`。部署生成的账号和 API 客户端凭据只保存在
以下被 Git 忽略、权限为 0600 的本机文件中：

```bash
cat /home/yuwk/favsync/secrets/wallabag-users.json
cat /home/yuwk/favsync/secrets/wallabag.json
```

不要把凭据复制到聊天或提交到 Git。新部署可参考 `wallabag.credentials.example.json` 创建 API
凭据文件。Favsync 使用专用 `novel` 账号，`wallabag.tags=[]` 表示该账号新增的全部条目都视为网页小说；
与其他用途共用账号时可配置标签列表。
更换 Wallabag 用户时应使用新的本地 `account` 标签；沿用旧标签会报 `wallabag_account_changed`。

在 Chrome 安装 Wallabagger 后填写同一 Wallabag 地址，以及 `secrets/wallabag.json` 中的
client ID、client secret、username 和 password。对动态页面或登录后页面，启用 Wallabagger 的
“保存时从浏览器获取正文”选项，让扩展提交当前已加载内容。保存后应在 Wallabag 列表中看到条目；
这一步与 NAS EPUB 导出是两个独立状态。浏览器无法访问 NAS 时，扩展应显示失败。

Favsync 完整分页读取 API，正文 HTML 指纹变化时覆盖同一个稳定文件，不因标题或标签变化制造副本：

```text
/vol3/1000/Picture/Downloads/Wallabag/标题_[条目ID].epub
```

写入时先使用隐藏临时目录，EPUB 必须通过 ZIP CRC、mimetype 与正文长度检查才会原子替换。
正文过短或疑似登录表单会保留为失败任务。正文内远程图片或缺失图片通过
`status.wallabag_exports.attachment_status=incomplete` 单独报告，正文导出状态仍按实际结果记录。

手动验收：

```bash
docker compose stop favsync
docker compose run --rm favsync --config /app/config.toml sync-once
docker compose run --rm favsync --config /app/config.toml status
find /vol3/1000/Picture/Downloads/Wallabag -maxdepth 1 -type f -name '*.epub' -printf '%f %s bytes\n'
docker compose up -d favsync
```

再次执行后，同一条目不得出现第二个文件；修改正文后应原子覆盖原路径。`status` 中
`wallabag_entries.scan_status`、bundle 错误和 `wallabag_exports` 分别表示分页扫描、导出任务及图片完整性。
