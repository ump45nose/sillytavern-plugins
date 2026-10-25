import { Select } from "../ui/Select";
import { useEffect, useState } from "react";
import { Activity, ArrowUpRight, Download, Info } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { Dialog, Empty } from "../ui/common";
const groups = [
  ["system", "系统", "var(--wb-trace-system)"],
  ["preset", "预设", "var(--wb-trace-preset)"],
  ["world", "世界书", "var(--wb-trace-world)"],
  ["character", "角色", "var(--wb-trace-character)"],
  ["history", "历史（含输入）", "var(--wb-trace-history)"],
  ["input", "输入", "var(--wb-trace-input)"],
];
const compact = (n: number | null | undefined) =>
  n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
export default function Trace({ host, trace }: { host: HostAdapter; trace: any }) {
  const [, tick] = useState(0),
    [id, setId] = useState(""),
    [full, setFull] = useState(false),
    [tab, setTab] = useState("messages"),
    [view, setView] = useState("parts");
  useEffect(() => {
    const timer = setInterval(() => tick((v) => v + 1), 750);
    return () => clearInterval(timer);
  }, []);
  const records = [...trace.records].reverse(),
    record = records.find((x) => x.id === id) || records[0];
  const counts: Record<string, number | null> = {
    system: 0,
    preset: 0,
    world: 0,
    character: 0,
    history: 0,
    input: null,
  };
  for (const [key, value] of Object.entries(record?.composition?.counts || {})) {
    const kind =
      key === "main"
        ? "system"
        : /^worldInfo/.test(key)
          ? "world"
          : /^(charDescription|charPersonality|scenario|personaDescription|dialogueExamples)$/.test(key)
            ? "character"
            : key === "chatHistory"
              ? "history"
              : "preset";
    if (typeof value === "number" && Number.isFinite(value)) counts[kind] = Number(counts[kind]) + value;
  }
  const hasCounts = record?.composition?.counts,
    total = Object.values(counts).reduce<number>((sum, n) => sum + (n || 0), 0);
  const hits = Array.isArray(record?.worldInfo) ? record.worldInfo : [];
  const time = (offset = 0) =>
    record?.timestamp
      ? new Date(record.timestamp + offset).toLocaleTimeString("zh-CN", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          fractionalSecondDigits: 3,
        })
      : "—";
  const details = (
    <>
      <div className="wb-tabs">
        {[
          ["messages", "实际请求"],
          ["world", "世界书"],
          ["assembled", "组装快照"],
        ].map(([key, label]) => (
          <button key={key} className={tab === key ? "is-active" : ""} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      <div className="wb-trace-body">
        {tab === "world" ? (
          hits.map((e: any, i: number) => (
            <details key={i} open>
              <summary>
                {e.world} / {e.comment || e.uid}
              </summary>
              <pre>{e.content}</pre>
            </details>
          ))
        ) : tab === "assembled" ? (
          <>
            <p className="wb-caption">{record?.assemblyEvent} · 后续插件可能继续修改</p>
            <pre>{JSON.stringify(record?.assembled, null, 2)}</pre>
          </>
        ) : (
          <>
            {record?.body?.messages?.map((m: any, i: number) => (
              <details key={i} open={i === 0}>
                <summary>
                  {i + 1} · {m.role}
                </summary>
                <pre>{typeof m.content === "string" ? m.content : JSON.stringify(m.content, null, 2)}</pre>
              </details>
            ))}
            <details>
              <summary>完整请求与参数</summary>
              <pre>{JSON.stringify(record?.body, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
    </>
  );
  const limit = record?.composition?.limit,
    scale = limit || total || 1,
    model = record?.body?.model,
    seconds = record?.elapsedMs == null ? null : `${(record.elapsedMs / 1000).toFixed(1)} s`,
    clock = (r: any) =>
      r?.timestamp
        ? new Date(r.timestamp).toLocaleTimeString("zh-CN", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        : "—",
    ok = record?.status === 200,
    { messages: _messages, ...params } = record?.body || {};
  return (
    <div className="wb-trace wb-tr">
      <header className="wb-tr-head">
        <h2>生成 Trace</h2>
        <Evidence text="仅本次会话内存 · 最多 20 条 · 敏感字段脱敏" />
        <span className="wb-grow" />
        {record && (
          <button
            className="wb-tr-clear"
            title="清空记录"
            onClick={() => {
              trace.clear();
              tick((v) => v + 1);
            }}
          >
            清空
          </button>
        )}
      </header>
      {!record ? (
        <Empty icon={<Activity size={18} />} title="还没有请求">
          发送消息后，可查看请求与世界书命中。
        </Empty>
      ) : (
        <>
          <div className="wb-tr-scroll">
            <div
              className={`wb-tr-pick${ok ? " is-ok" : record.status === "pending" ? " is-pending" : " is-error"}`}
            >
              <Select aria-label="选择请求记录" value={record.id} onChange={(e) => setId(e.target.value)}>
                {records.map((r, i) => (
                  <option value={r.id} key={r.id}>
                    {[
                      `#${records.length - i}`,
                      clock(r),
                      r.body?.model,
                      r.status === 200
                        ? r.elapsedMs == null
                          ? null
                          : `${(r.elapsedMs / 1000).toFixed(1)} s`
                        : r.status === "pending"
                          ? "等待响应"
                          : `HTTP ${r.status}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </option>
                ))}
              </Select>
            </div>
            <div className="wb-rail-segment wb-tr-views" role="group" aria-label="Trace 视图">
              {[
                ["parts", "构成"],
                ["messages", "消息"],
                ["world", "世界书"],
                ["params", "参数"],
              ].map(([key, label]) => (
                <button key={key} aria-pressed={view === key} onClick={() => setView(key)}>
                  {label}
                </button>
              ))}
            </div>
            {view === "parts" ? (
              <section className="wb-tr-parts-view" aria-label="上下文构成">
                <div className="wb-tr-total">
                  <span>
                    输入合计
                    <Evidence
                      text={
                        hasCounts
                          ? "组装阶段 · 原生分词计数；输入已计入历史，未单独拆分。"
                          : "本次请求未取得原生分词构成。"
                      }
                    />
                  </span>
                  <strong>{hasCounts ? total.toLocaleString() : "—"}</strong>
                  <small>/ {compact(limit)} tokens</small>
                </div>
                <div className="wb-tr-bar" aria-label="组装快照的 Token 构成">
                  {groups.map(([key, label, color]) =>
                    counts[key] ? (
                      <span
                        key={key}
                        title={`${label} ${compact(counts[key])}`}
                        style={{ background: color, width: `${(Number(counts[key]) / scale) * 100}%` }}
                      />
                    ) : null,
                  )}
                </div>
                {limit ? (
                  <div className="wb-tr-scale" aria-hidden="true">
                    <span>0</span>
                    <span>{compact(limit / 2)}</span>
                    <span>{compact(limit)}</span>
                  </div>
                ) : null}
                <div className="wb-tr-table-head" aria-hidden="true">
                  <span>部分</span>
                  <span>Tokens</span>
                  <span>占比</span>
                </div>
                <div className="wb-tr-parts">
                  {groups.map(([key, label, color]) => (
                    <div key={key}>
                      <i style={{ background: color }} />
                      <span>{label}</span>
                      <code>
                        {hasCounts && counts[key] != null ? Number(counts[key]).toLocaleString() : "—"}
                      </code>
                      <em>
                        {hasCounts && counts[key] != null && total
                          ? `${((Number(counts[key]) / total) * 100).toFixed(1)}%`
                          : "—"}
                      </em>
                    </div>
                  ))}
                </div>
                <dl className="wb-tr-stats">
                  <div>
                    <dt>
                      响应头
                      <Evidence text="浏览器发出请求到收到响应头的时间；未采集首字时间与流式速率。" />
                    </dt>
                    <dd>{seconds ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>消息</dt>
                    <dd>{record.body?.messages?.length ?? "—"} 条</dd>
                  </div>
                  <div>
                    <dt>
                      世界书命中
                      {record.worldInfoEvidence !== "WORLD_INFO_ACTIVATED" && (
                        <Evidence text="未观察到命中事件，不等同于没有命中。" />
                      )}
                    </dt>
                    <dd>{hits.length} 条</dd>
                  </div>
                </dl>
                <p className="wb-tr-note">
                  {time()} 发送 · {record.status === "pending" ? "等待响应" : `HTTP ${record.status}`}
                  {model ? ` · ${model}` : ""}
                </p>
              </section>
            ) : view === "world" ? (
              <section className="wb-tr-list" aria-label="世界书命中">
                {hits.length === 0 && <p className="wb-tr-none">本次请求没有观察到世界书命中。</p>}
                {hits.map((entry: any, i: number) => (
                  <details className="wb-tr-item" key={i}>
                    <summary>
                      <span>{entry.comment || entry.world || `条目 ${entry.uid}`}</span>
                      <small>{entry.constant ? "常驻" : entry.vectorized ? "向量化" : "关键词"}</small>
                      <code>{entry.position === 4 ? `@D${entry.depth ?? "—"}` : ""}</code>
                    </summary>
                    <p className="wb-tr-evidence">
                      配置关键词：{(entry.key || []).join(" · ") || "无"}
                      <Evidence text="事件未提供实际命中词，这里列出的是条目配置的关键词。" />
                    </p>
                    <pre>{entry.content}</pre>
                  </details>
                ))}
              </section>
            ) : view === "messages" ? (
              <section className="wb-tr-list" aria-label="请求消息">
                {(record.body?.messages || []).map((m: any, i: number) => (
                  <details className="wb-tr-item" key={i} open={i === 0}>
                    <summary>
                      <span>
                        {i + 1} · {m.role}
                      </span>
                      <small>{typeof m.content === "string" ? `${m.content.length} 字` : ""}</small>
                    </summary>
                    <pre>
                      {typeof m.content === "string" ? m.content : JSON.stringify(m.content, null, 2)}
                    </pre>
                  </details>
                ))}
              </section>
            ) : (
              <section className="wb-tr-list" aria-label="请求参数">
                <pre className="wb-tr-json">{JSON.stringify(params, null, 2)}</pre>
              </section>
            )}
          </div>
          <footer className="wb-tr-foot">
            <button
              className="wb-tr-link"
              onClick={() => {
                setTab("messages");
                setFull(true);
              }}
            >
              查看完整 Prompt
              <ArrowUpRight size={14} />
            </button>
            <span className="wb-grow" />
            <button
              className="wb-panel-action"
              onClick={() =>
                host.download(
                  new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }),
                  `trace-${record.id}.json`,
                )
              }
            >
              <Download size={15} />
              导出 JSON
            </button>
          </footer>
        </>
      )}
      {full && record && (
        <Dialog title="完整 Prompt · 浏览器请求" wide onClose={() => setFull(false)}>
          <div className="wb-trace-full">{details}</div>
        </Dialog>
      )}
    </div>
  );
}

/** How a Trace figure was collected: required by the trace design, shown on demand. */
function Evidence({ text }: { text: string }) {
  return (
    <span className="wb-evidence" role="note" tabIndex={0} aria-label={text} title={text}>
      <Info size={14} />
    </span>
  );
}
