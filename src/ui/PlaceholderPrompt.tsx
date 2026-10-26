import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { HostAdapter } from "../host/adapter";
import type { PlaceholderRequest } from "../host/placeholder-runtime";
import { Dialog } from "./common";

const clip = (text: string) => (text.length > 15 ? text.slice(0, 15) + "..." : text);

/** Asks for the prompted placeholders of one expansion; it opens over native popups such as /buttons. */
export function PlaceholderPrompt({ host }: { host: HostAdapter }) {
  const runtime = host.placeholders;
  const request = useSyncExternalStore(runtime.subscribe, () => runtime.request);
  return request ? (
    <PromptDialog key={request.inputs.map((i) => i.name).join("\n")} request={request} />
  ) : null;
}

function PromptDialog({ request }: { request: PlaceholderRequest }) {
  const { inputs, vars, resolve } = request;
  // Fields start at the current values, as in the original script; an emptied field falls back.
  const [values, setValues] = useState(() => inputs.map((p) => vars[p.name] ?? ""));
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    first.current?.select();
  }, []);
  const submit = () => resolve(values.map((v) => v.trim()));
  return (
    <Dialog title="设置变量" onClose={() => resolve(null)}>
      <form
        className="wb-placeholder-prompt"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="wb-placeholder-fields">
          {inputs.map((p, i) => (
            <label key={p.name} className="wb-field">
              <strong>{p.prompt}</strong>
              <small>
                {[
                  `变量：${p.name}`,
                  p.fallback && `默认：${p.fallback}`,
                  vars[p.name] && `当前：${clip(vars[p.name])}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
              <input
                ref={i === 0 ? first : undefined}
                value={values[i]}
                placeholder={p.fallback || "请输入..."}
                onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
              />
            </label>
          ))}
        </div>
        <footer className="wb-flex">
          <span className="wb-grow" />
          <button type="button" onClick={() => resolve(null)}>
            取消
          </button>
          <button type="submit" className="wb-primary">
            确认
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
