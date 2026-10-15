import { useState } from "react";
import type { HostAdapter } from "../host/adapter";
import { useHost, useTask, Field, Notice } from "../ui/common";
export default function ResourceCenterPanel({ host }: { host: HostAdapter }) {
  const snap = useHost(host),
    task = useTask(),
    s = host.centerSettings();
  const [url, setUrl] = useState(s.url),
    [token, setToken] = useState(s.token),
    [channel, setChannel] = useState("");
  const profileId = snap.current.connection,
    binding = s.bindings[profileId],
    remote = host.center.connections.find((c) => c.id === binding?.channelId);
  const profile = snap.resources.connection.find((p) => p.id === profileId);
  return (
    <section className="wb-connection-quick">
      <div className="wb-section-title">AI 资源中心 · RP 手动管理</div>
      <Field label="中心地址">
        <input value={url} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <Field label="限定 RP 连接的凭据">
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </Field>
      <div className="wb-connection-actions">
        <button
          disabled={task.busy}
          onClick={() => task.run(() => host.configureCenter(url, token))}
        >
          保存并读取
        </button>
        <button
          disabled={task.busy || !s.url}
          onClick={() => task.run(() => host.center.read())}
        >
          读取中心
        </button>
      </div>
      <small>
        当前原生连接：{profile?.name || "未选择"} ·{" "}
        {binding ? "禁测活" : "未绑定"}；同步只保存明确的连接字段。
      </small>
      {host.center.connections.length > 0 && (
        <Field label="绑定中心 RP 连接">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">请选择</option>
            {host.center.connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.baseUrl}
              </option>
            ))}
          </select>
          <button
            disabled={!channel || !profileId || task.busy}
            onClick={() => task.run(() => host.bindCenter(profileId, channel))}
          >
            关联当前连接
          </button>
        </Field>
      )}
      {binding && (
        <>
          <div>
            酒馆已确认 v{binding.version} · 中心{" "}
            {remote ? `v${remote.version}` : "尚未读取"} ·{" "}
            {binding.enabled ? "启用" : "暂停"}
          </div>
          {remote && remote.version !== binding.version && (
            <div className="wb-notice">
              中心待应用：{remote.baseUrl} · {remote.models.join(", ")}
              （保存到原生连接，不切换当前生成）
            </div>
          )}
          <button
            disabled={task.busy}
            onClick={() =>
              task.run(async () => {
                binding.signature = undefined;
                await host.center.queueSavedProfiles();
              })
            }
          >
            以酒馆已保存配置为准上报
          </button>
          <button
            disabled={task.busy || snap.busy}
            onClick={() => task.run(() => host.applyCenter(profileId))}
          >
            应用中心连接到原生保存
          </button>
        </>
      )}
      <p>
        待交保存 {s.outbox.length} 条 · 最近确认 {s.lastAck || "无"}
      </p>
      <button
        disabled={task.busy || !s.outbox.length}
        onClick={() => task.run(() => host.center.deliver())}
      >
        重交保存结果
      </button>
      <Notice error={task.error || s.error} />
    </section>
  );
}
