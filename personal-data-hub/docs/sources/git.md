# GitHub 采集与阅读

实现：`remote.GitCollector` → `git_activity`；沿用当前 GitHub MCP、OAuth/密钥引用和出站配置。来源仍为 git，提交身份仍为 repo + sha，不迁移原有记录。

| 内容 | 采集范围 | 阅读规则 |
| --- | --- | --- |
| git_commit | 当前鉴权用户作为作者、鉴权可见仓库默认分支中的提交，按 committer-date 查询 | 现有 business-v1；完整提交消息、仓库、sha 和源链接 |
| git_pull_request | 用户创建的 PR，按 updated 查询后读取真实 PR 详情 | git-pr-v1；完整描述、当前 state/draft/merged、源端时间、分支及链接 |

每轮固定 UTC 秒级查询上界；成功后提交 completed_through / pr_completed_through。默认回看 72 小时，每 7 天对账最近 30 天。旧 collected_at 可作为提交水位迁移起点；首次 PR 接入默认取最近 30 天。`reconcile` 或明确 `--since` 可补采，不能靠近期搜索推断源端删除。

搜索超过 1000 条或报告不完整时，按秒级时间范围拆分再分页；每段最多 10 页。单秒仍超过上限则明确失败，需要设置 repositories 范围，不推进水位。窗口失败可能已有部分原件提交，稳定身份支持重跑。PR 状态读取使用当前对象，updated_at 是源端更新时间，Hub 的观察时间不作为状态转换时间。

目前没有采集所有本地仓库、非默认分支的完整提交、别人创建但用户参与的 PR、评审、Issue、完整 PR 事件流。较晚推送的旧提交可能超过回看/对账范围，需要明确补采。搜索分页不是源端的冻结快照。

私有配置可设置 repositories；保持现有 profile_root、secret_env、proxy_env 和账户。新增参数只控制窗口与 PR 范围，不复制凭据。

依据：[GitHub 提交搜索范围](https://docs.github.com/en/search-github/searching-on-github/searching-commits)、[日期查询支持秒级时间](https://docs.github.com/en/search-github/getting-started-with-searching-on-github/understanding-the-search-syntax)。现有 MCP 的 search_commits、search_pull_requests、pull_request_read 工具结构已读取确认；功能验收统一留到采集侧末尾。
