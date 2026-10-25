import { useSyncExternalStore } from "react";
import { Plug } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";

const routes = { page: "经本页面写入", disk: "直写磁盘", none: "无变化" } as const;
const time = (ms: number) => new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });

/** The 「IDE 同步」 card: whether the server plug-in is there, who is connected, the latest writes. */
export default function SyncStatus({ host }: { host: HostAdapter }) {
  const sync = host.sync,
    state = useSyncExternalStore(sync.subscribe, () => sync.state),
    online = state.status === "online";
  const summary =
    state.status === "probing"
      ? "正在检查服务端插件…"
      : state.status === "absent"
        ? "未检测到 workbench-sync 服务端插件"
        : state.status === "reconnecting"
          ? "与插件的连接中断，正在重连…"
          : `VS Code 连接 ${state.clients} 个${state.pages > 1 ? ` · 另有 ${state.pages - 1} 个工作台页面` : ""}`;
  return (
    <article className={`wb-addon-card wb-sync-card ${online ? "is-enabled" : ""}`} aria-label="IDE 同步">
      <header>
        <span className="wb-addon-icon" aria-hidden="true">
          <Plug size={19} />
        </span>
        <strong>IDE 同步</strong>
      </header>
      {state.status === "absent" ? (
        <p>
          在 VS Code 里以可读文件编辑世界书、角色、预设、连接、用户设定和大纲。需要酒馆 config.yaml 中
          <code>enableServerPlugins: true</code>，并把 workbench-sync 放进 plugins/ 后重启酒馆。
        </p>
      ) : (
        <p>VS Code 保存的文件由本页面经现有保存流程写入；页面里未保存的草稿不会被覆盖，保存时按字段合并。</p>
      )}
      {state.recent.length > 0 && (
        <ul className="wb-sync-recent" aria-label="最近同步">
          {state.recent.slice(0, 5).map((r, i) => (
            <li key={i} className={r.ok ? "" : "is-error"}>
              <time>{time(r.time)}</time>
              <span title={r.path}>{r.path}</span>
              <small>{r.ok ? routes[r.route] : "失败"}</small>
              {r.message && <em>{r.message}</em>}
            </li>
          ))}
        </ul>
      )}
      <footer>
        <span>{online ? "插件在线" : state.status === "absent" ? "未启用" : "连接中"}</span>
        <small>{summary}</small>
      </footer>
    </article>
  );
}
