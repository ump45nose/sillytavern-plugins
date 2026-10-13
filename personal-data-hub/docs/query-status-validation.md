# 列表载荷与 Skysight 状态修正验收

2026-10-06 在 NAS 与 Mac 完成部署验证，代码提交 `d149fb4`，Mac 客户端版本 `0.2.1`。

## 采集状态

原 `skysight-raw` 最近多轮没有新增异常，却因检查点保留的 24 个无效片段一直被标为 `partial`。这 24 条历史文件包含 15 条 JSON 解析失败和 9 条片段校验失败，已保留原始文件和异常记录。

现在 `last_run` 只报告本轮采集结果：本轮发现无效片段时为 `partial` / `segment_invalid`，成功且没有本轮异常时为 `ok` / `error=null`。归档中的历史异常单独通过 `quality_warnings=[{"code":"historical_segment_invalid","count":24}]` 报告，不重写旧运行记录。Mac 分别显示绿色“正常”与橙色“历史异常 24 条，原始文件已保留”。

线上 CRM MCP 与 HTTPS API 验证最新 `skysight-raw` 状态均为 `ok`，历史提示数量仍为 24。未删除或修改这 24 个原始片段。

## 列表响应

`list_data_records` 和 `GET /api/v1/records` 默认 `include_content=false`，只读取 ID、来源、类型、时间、标题及摘要。标题最多 160 字符，摘要最多 500 字符；没有 `raw`、`normalized` 或附件字段。记录正文从 `get_data_record` / `GET /api/v1/records/{id}` 获取；显式传 `include_content=true` 可取得原来的完整字段。

列表返回 `total` 与 `next_offset`，最后一页不会给出多余的下一页。来源、类型、原分页及 MCP 时间筛选保留；HTTP 列表增加与查看接口相同的带时区时间筛选。下一页探测只读摘要，不额外读取一条大载荷。

生产实测 `skysight-raw` 的两条记录：

| 入口 | 默认摘要 | 显式完整载荷 |
| --- | --- | --- |
| CRM MCP，沿用现有 OAuth | 676 字符 | 本地实际 FastMCP 客户端验证开关与详情完整性 |
| NAS LAN API | 696 字符 / 字节 | 2,136,711 字符 |
| 原公网 HTTPS API | 696 字符 / 字节 | 2,136,711 字符 |

两条列表 ID 与显式完整模式一致，完整模式的记录与详情接口逐字段相同。16 个来源的默认列表均不含完整载荷；只读 token 仍不能写入。测量值对应验收时的数据，后续采集会改变列表内容与长度。

## 验证与部署

- `checks/query-status-smoke.py`：真实 HTTP / FastMCP 客户端验证大载荷默认边界、显式开关、详情、分页、时间筛选，以及新增异常、本轮成功、缓存消失和来源修复时的状态变化。
- `checks/stage2-smoke.py`：查看端权限、摘要搜索、附件、NUL 原始内容保留及财务推送兼容通过；Python 编译和 `git diff --check` 通过。
- NAS 镜像 `local/personal-data-hub:0.2.1-query`，SHA-256 `5c7bdb81bd268413442f77a0422d751f259179b48025b11b48e2860cd8c2317f`；88 个安装依赖兼容检查通过。
- 原 Compose 项目仅替换 `crm` 镜像，候选清单在 `releases/personal-data-hub-0.2.1-query/compose.yaml`；原入口、OAuth 和 Tunnel 的 `mcpctl` 校验通过。统一采集、Health / 财务接收与 ShellCrash 服务均为 active。
- Mac 原位构建安装，现有 Keychain 配置可用；原两个 Agent 均已加载。原生验收读取 16 个来源、52,656 条记录、27 种类型，附件 SHA-256 校验通过。1240×780 窗口显示正常，历史异常提示已目视检查。

上一版镜像、Compose 候选清单与 Mac 应用备份保留。无需数据迁移，不修改已有原始载荷、凭据、OAuth 身份或来源授权。
