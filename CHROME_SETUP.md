# Chrome 自动同步接入

CookieCloud 接收端应绑定 NAS 的局域网地址，例如 `http://NAS_LAN_IP:18088`。Chrome 所在电脑需要能访问该地址；Favsync 默认每 8 小时取回一次。

1. 从 [Chrome 商店](https://chrome.google.com/webstore/detail/cookiecloud/ffjiejobkoibkjlhjnlgmcnnigeelbdl)安装 CookieCloud（[官方项目](https://github.com/easychen/CookieCloud)）。
2. 在 Chrome 登录需要同步的 X、小红书及 EH/ExHentai 账号。
3. 在 NAS 终端查看本机凭据文件，不要把内容发到聊天或截图公开：

   ```bash
   cat secrets/cookiecloud.json
   ```

4. 扩展选择上传模式，填写：

   | 扩展设置 | 值 |
   | --- | --- |
   | 服务器地址 | `http://NAS_LAN_IP:18088` |
   | 用户 KEY | 凭据文件中的 `uuid` |
   | 端对端加密密码 | 凭据文件中的 `password` |
   | 同步域名关键词 | `x.com`、`twitter.com`、`xiaohongshu.com`、`e-hentai.org`、`exhentai.org` |
   | 同步间隔 | 8 小时 |
   | LocalStorage 同步 | 关闭 |

   下载器兼容 legacy 和 aes-128-cbc-fixed 两种加密格式，以及接收端不返回算法标记的情况。

5. 保存设置并点击手动同步。扩展显示上传成功后，告知本任务检查；无需提供 KEY 或密码。
6. 确认取回的 Cookie 可解密、包含 X 登录字段、账号匹配后，再将 `config.toml` 的 `[cookiecloud] enabled` 改成 `true`，重启下载器。不要在首次上传前启用，以免产生无意义的取回失败。

```bash
cd /path/to/favsync
docker compose restart favsync
docker compose exec -T favsync favsync --config /app/config.toml status
```

验收时查看 `cookiecloud` 是否为 `ok`、`cookiecloud_last_success` 是否更新，以及 X 来源的后续扫描结果。HTTP 200 或插件提示成功不能代替真实取回验证。

浏览器关闭时不能提供新的 Cookie；X 登录失效后仍需在 Chrome 重新登录。同步失败时保留原 Cookie。两个 Telegram 账号使用各自会话，不依赖 CookieCloud。
