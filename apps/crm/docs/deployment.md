# 部署与一次性迁移

沿用现有容器、PostgreSQL、OAuth 状态、API/viewer 令牌和附件卷。新业务表使用 crm_ 前缀；旧表只用于迁移和备份，不再写入或镜像。

## 切换顺序

1. 备份数据库及现有配置，暂停微信采集和 CRM 镜像任务；保留原成功 checkpoint、媒体队列和 spool。
2. 使用候选镜像执行 `personal-crm migrate` 创建新表。
3. 设置 `CRM_ASSET_ROOT` 为既有 Hub 附件卷目录（统一服务直接使用其 asset_root），执行 `personal-crm migrate-legacy`。
4. 核对转换报告中的人物、消息、手工记录、跳过记录与交互数，检查关键内容和附件。
5. 关闭 sources 中的 crm / crm_pg 镜像来源，启动候选服务；微信采集改用新入口并接续原 checkpoint。
6. 验证读写权限、真实私聊新增、分段及 MCP 读取，再恢复其余原运行入口。

迁移不删除旧记录。归档非空时拒绝重复转换，以免覆盖用户新写入；失败事务回滚后可以修复再跑。没有读取微信历史、猜测人物或复杂迁移框架。

## 配置

- `WECHAT_INTERACTION_GAP_MINUTES=30`：服务端分段间隔，改配置不重组既有正文。
- `CRM_ASSET_ROOT`：独立 CRM 服务附件目录；统一服务使用 Hub 既有 asset_root。
- `CRM_WEBHOOK_URL=https://你的域名/api/v1/crm/ingest/wechat`：Mac 出站地址，沿用原 webhook token。
- `CRM_CHECKPOINT` / `CRM_CLIENT_ID` / `CRM_ACCOUNT_NAMESPACE`：沿用原值。新的无水位设备从启用时间起采集，不默认回填。
- `WECHAT_MEDIA_ENABLED=true`：复用原媒体队列和被动读取能力，不增加 OCR、转写或解密。

旧 URL 配置在采集器启动时转换为新入口；服务端不保留旧业务 Webhook。正文批量写入最多 500 条，同步标识必须使用现有包含账号及会话的稳定消息键。

## 回退

恢复原服务镜像和采集代码，保留当前新表、旧表、附件及 OAuth。部署记录保存切换时的旧 checkpoint 副本；只在确认需要重新交付切换期间消息给旧系统时使用，不把回退误当成清空归档。新系统的手工写入仍在新表中，不能靠恢复旧库覆盖它们。

旧提醒、Fact、指标、仓储及相关测试已从当前源码移除，可从 Git 历史查阅。旧表模型仅用于历史迁移和数据库备份，不参与业务写入。

## 只更新已安装 Mac 的微信采集组件

不重建界面或替换已获准的凭据助手。以下命令使用本机既有签名身份，将采集代码放入已安装应用，验证原后台读取入口，再切换微信任务；原 checkpoint、媒体队列和设备身份保持不变。

```bash
python3 apps/mac-client/update-wechat.py --prepare /tmp/crm-collector-candidate.app
python3 apps/mac-client/update-wechat.py --check /tmp/crm-collector-candidate.app
python3 apps/mac-client/update-wechat.py --install /tmp/crm-collector-candidate.app
```

默认应用在 `~/Applications/Personal Data Hub.app`。若安装在 `/Applications`，三次命令都加 `--app "/Applications/Personal Data Hub.app"`。安装会保存旧应用和任务配置，失败恢复原入口，不重启其他采集任务。
