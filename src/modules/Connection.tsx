import React, { useEffect, useReducer } from "react";
import { FlaskConical, PlugZap, RefreshCw } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { useTask, Notice, useHostSlices, withoutChat } from "../ui/common";
import DesignedSettings from "./DesignedSettings";
import { Select } from "../ui/Select";

export function ConnectionRuntime({ host }: { host: HostAdapter }) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    [, redraw] = useReducer((n) => n + 1, 0);
  const state = host.connectionControls(),
    typed = state.model?.value ?? "";
  useEffect(() => host.watchConnectionControls(redraw), [host]);
  useEffect(
    () => host.decorateConnectionControls(),
    [host, state.main.id, state.provider?.value, state.model?.id, state.pick?.id],
  );
  const field = (control: NonNullable<typeof state.model>, label: string) =>
    control.type === "select" ? (
      <Select
        aria-label={label}
        value={control.value}
        disabled={control.disabled || snap.busy}
        onChange={(e) => task.run(() => host.setConnectionControl(control.id, e.target.value))}
      >
        {control.options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {control.id === state.pick?.id && !o.value ? "从可用模型中选择…" : o.label}
          </option>
        ))}
      </Select>
    ) : (
      <input
        aria-label={label}
        value={control.value}
        disabled={control.disabled || snap.busy}
        placeholder="输入模型 ID"
        onChange={(e) => host.setConnectionControl(control.id, e.target.value)}
      />
    );
  const row = (label: string, control: React.ReactNode) => (
    <div className="wb-card-row">
      <span className="wb-card-label">{label}</span>
      {control}
    </div>
  );
  return (
    <>
      {/* The live connection, not the profile on screen: profiles record it (board "PanelConnection"). */}
      <section className="wb-card wb-connection-card" aria-label="当前 API 连接">
        {row("接口类型", field(state.main, "接口类型"))}
        {state.provider && row("服务商", field(state.provider, "服务商"))}
        {row(
          "模型",
          <div className="wb-connection-pick">
            {state.model && state.pick ? (
              <div className="wb-connection-models">
                {/* A typed ID that is not listed leaves the list on its prompt, so any listed model can be chosen. */}
                {field(
                  {
                    ...state.pick,
                    value: state.pick.options.some((o) => o.value && o.value === typed) ? typed : "",
                  },
                  "可用模型",
                )}
                {field(state.model, "运行模型")}
              </div>
            ) : state.model ? (
              field(state.model, "运行模型")
            ) : (
              <input aria-label="运行模型" value="由后端选择，可在下方配置" readOnly />
            )}
            <button
              className="wb-panel-icon"
              title="刷新模型"
              aria-label="刷新模型"
              disabled={snap.busy || task.busy || state.connecting}
              onClick={() => task.run(() => host.click(`#${state.connect}`))}
            >
              <RefreshCw size={15} />
            </button>
          </div>,
        )}
        <div className="wb-connection-bar">
          <button
            className="wb-connection-go"
            disabled={snap.busy || task.busy || state.connecting}
            onClick={() => task.run(() => host.click(`#${state.connect}`))}
          >
            <PlugZap size={14} />
            {state.connecting ? "连接中…" : "连接"}
          </button>
          {state.test && (
            <button
              className="wb-connection-test"
              disabled={snap.busy || task.busy || state.connecting}
              title="发送测试消息，使用当前 API"
              onClick={() => task.run(() => host.click(`#${state.test}`))}
            >
              <FlaskConical size={14} />
              测试
            </button>
          )}
          <small className={snap.online ? "is-online" : ""}>{snap.online ? "已连接" : "未连接"}</small>
        </div>
      </section>
      <Notice error={task.error} />
      <DesignedSettings host={host} page="connection" group="服务与凭据" />
    </>
  );
}
