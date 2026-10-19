# Plaud Archive 宿主入口

业务源码在聚合仓库 `personal-info/plaud-archive/`，本目录只维护 systemd。既有 Lingjun 作业 `58d4a4c46d49` 和可信 `scripts/plaud-daily.sh` 保持身份；`model/plaud-daily.sh` 调用独立 CLI。

私有 `/home/yuwk/cron/env/plaud-archive.env` 仅配置 `PLAUD_PYTHON` 和 `PLAUD_CONFIG` 两个绝对路径。API 与作业均使用 Hermes 988:984，数据根目录 `/vol1/1000/plaud-archive`。配置、模型密钥与 OAuth 状态不进入 Git。

只安装此任务包装：

```sh
python3 deploy-hermes.py --only model/plaud-daily.sh
install -m 0644 plaud-archive/systemd/plaud-archive.service /home/yuwk/cron/systemd/plaud-archive.service
sudo ln -sfn /home/yuwk/cron/systemd/plaud-archive.service /etc/systemd/system/plaud-archive.service
sudo systemctl daemon-reload
sudo systemctl enable --now plaud-archive.service
```

安装源码不修改 Hermes 私有作业。迁移期间旧作业暂停；历史音频和新稿验收完成后，沿用原 ID 恢复每 30 分钟检查，应用内部从 07:30 开始处理昨天。失败步骤最多三次、间隔 30 分钟。手动续跑使用应用 CLI `retry --date YYYY-MM-DD` 后 `run-day`，成功步骤保留。

当前源码入口为 `/vol1/1000/Code/personal-info/plaud-archive`，由独立聚合 worktree 提供。主树集成后保持该入口；部署路径更新不代表恢复已暂停的作业。
