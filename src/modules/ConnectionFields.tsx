import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import {
  Copy,
  Download,
  KeyRound,
  PencilLine,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  Trash2,
  Upload,
  Volume2,
} from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { Field, Notice } from "../ui/common";
import { HostControl, type FormControl } from "../ui/HostControl";
import { Fold } from "../ui/ResourceControls";
import { nativePages } from "./NativeSettings";
const titles: Record<string, string> = {
  custom_api_url_text: "API 地址",
  custom_prompt_post_processing: "提示词后处理",
  "auto-connect-checkbox": "自动连接上次使用的服务",
  openai_reverse_proxy: "代理地址",
  openai_reverse_proxy_name: "代理名称",
  openai_proxy_password: "代理凭据",
  server_urls_text: "服务地址",
  vertexai_auth_mode: "认证方式",
  vertexai_service_account_json: "服务账号 JSON",
};
const actionTitles: Record<string, string> = {
  "Manage API keys": "管理 API 凭据",
  "Additional Parameters": "附加请求参数",
  "Validate JSON": "验证并保存 JSON",
  "Update current template": "更新模板",
  "Rename current template": "重命名模板",
  "Save template as": "另存模板",
  "Restore current template": "还原模板",
  "Delete template": "删除模板",
};
function clean(s: string | null | undefined) {
  return (s || "").replace(/\s+/g, " ").trim();
}
function labelOf(n: HTMLElement) {
  const input = n as FormControl,
    l = input.labels?.[0]?.cloneNode(true) as HTMLElement | undefined;
  l?.querySelectorAll("input,select,textarea,button,.menu_button").forEach((n) => n.remove());
  const previous = n.previousElementSibling;
  const adjacent =
    previous && !previous.matches("select,input,textarea,.menu_button") ? clean(previous.textContent) : "";
  return (
    titles[n.id] ||
    (/api_key|access_token|auth_token/.test(n.id) ? "API 凭据" : "") ||
    clean(l?.textContent) ||
    n.getAttribute("aria-label") ||
    n.title ||
    clean(n.closest(".range-block")?.querySelector(".range-block-title")?.textContent) ||
    adjacent ||
    n.getAttribute("placeholder") ||
    (n.matches("select,input,textarea") ? "" : clean(n.textContent)) ||
    n.id
  );
}
function iconOf(n: HTMLElement) {
  const s = (n.id + " " + n.className + " " + n.title + " " + n.dataset.action).toLowerCase();
  return /delete|trash|remove/.test(s)
    ? Trash2
    : /import|upload/.test(s)
      ? Upload
      : /export|download/.test(s)
        ? Download
        : /new|create|add/.test(s)
          ? Plus
          : /refresh|update/.test(s)
            ? RefreshCw
            : /restore|reset/.test(s)
              ? RotateCcw
              : /copy|duplicate/.test(s)
                ? Copy
                : /save/.test(s)
                  ? Save
                  : /rename|edit/.test(s)
                    ? PencilLine
                    : /key|secret/.test(s)
                      ? KeyRound
                      : /audio|sound/.test(s)
                        ? Volume2
                        : Settings;
}
function applicable(n: HTMLElement, root: HTMLElement) {
  for (let p: HTMLElement | null = n; p && p !== root; p = p.parentElement) {
    if (p === n && p.matches("input[type=checkbox],input[type=radio]")) continue;
    if (p.hidden) return false;
    if (p.classList.contains("inline-drawer-content") || p.matches("details")) continue;
    if (getComputedStyle(p).display === "none" && !p.matches("select.select2-hidden-accessible"))
      return false;
  }
  return true;
}
const credentials =
  /url|api_key|access_token|auth_token|password|region|project|tenant|deployment|vertexai_auth_mode|vertexai_service_account_json/;
const isCredentialControl = (n: FormControl) =>
  credentials.test(n.id) || (n.id === "openai_reverse_proxy" && Boolean(n.value));
const isCredentialAction = (n: HTMLElement) =>
  n.classList.contains("manage-api-keys") || n.id === "vertexai_validate_service_account";
/** The connection fields the runtime card does not mirror, without displaying the original page container. */
export default function ConnectionFields({ host }: { host: HostAdapter }) {
  const ref = useRef<HTMLDivElement>(null),
    [root, setRoot] = useState<HTMLElement | null>(null),
    [error, setError] = useState(""),
    [, redraw] = useReducer((n) => n + 1, 0);
  useLayoutEffect(() => {
    let restore: undefined | (() => void);
    try {
      restore = host.leaseNative(nativePages.connection.id, ref.current!);
      setRoot(ref.current!.firstElementChild as HTMLElement);
    } catch (e) {
      setError(String(e));
    }
    return () => {
      restore?.();
      setRoot(null);
    };
  }, [host]);
  useEffect(() => {
    if (!root) return;
    let frame = 0;
    const sync = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(redraw);
    };
    const observer = new MutationObserver(sync);
    observer.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["style", "hidden", "class", "disabled"],
    });
    root.addEventListener("input", sync);
    root.addEventListener("change", sync);
    const unsub = host.subscribe(sync);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      unsub();
      root.removeEventListener("input", sync);
      root.removeEventListener("change", sync);
    };
  }, [root, host]);
  const c = host.connectionControls(),
    bridged = [
      c.main?.id,
      c.provider?.id,
      c.model?.id,
      c.connect,
      c.test,
      "connection_profiles",
      "view_connection_profile",
      "create_connection_profile",
      "update_connection_profile",
      "edit_connection_profile",
      "reload_connection_profile",
      "delete_connection_profile",
    ];
  const owns = (n: HTMLElement) =>
    !!root && applicable(n, root) && !bridged.includes(n.id) && !n.closest(".wb-connection-bridged");
  const controls = root
    ? [...root.querySelectorAll<FormControl>("input,textarea,select")].filter(
        (n) =>
          owns(n) &&
          n.type !== "hidden" &&
          !n.id.endsWith("_pin") &&
          !n.id.endsWith("_counter") &&
          !n.classList.contains("select2-search__field") &&
          !n.closest(".wb-select"),
      )
    : [];
  const actions = root
    ? [
        ...root.querySelectorAll<HTMLElement>(
          "button,.menu_button,a.menu_button,label.menu_button,[role=tab]",
        ),
      ].filter(
        (n) =>
          owns(n) &&
          !n.closest(".select2-container,.inline-drawer-header") &&
          !n.classList.contains("drawer-toggle") &&
          !n.parentElement?.closest("button,.menu_button") &&
          !n.closest("label:has(input[type=checkbox]),label:has(input[type=radio])"),
      )
    : [];
  const renderControl = (n: FormControl) => {
    const label = labelOf(n),
      isCheck = n instanceof HTMLInputElement && /checkbox|radio/.test(n.type);
    return (
      <div
        key={n.id || controls.indexOf(n)}
        className={`wb-designed-field ${isCheck ? "is-check" : ""} ${n instanceof HTMLTextAreaElement || (n instanceof HTMLSelectElement && n.multiple) ? "is-full" : ""}`}
        data-control={n.id}
      >
        {isCheck ? (
          <label className="wb-check">
            <HostControl node={n} host={host} label={label} />
            <span>{label}</span>
          </label>
        ) : (
          <Field label={label}>
            <HostControl node={n} host={host} label={label} />
            {n instanceof HTMLInputElement && n.type === "range" && <output>{n.value}</output>}
          </Field>
        )}
      </div>
    );
  };
  const renderAction = (n: HTMLElement, i: number) => {
    const Icon = iconOf(n),
      label =
        actionTitles[clean(n.textContent)] ||
        actionTitles[n.title] ||
        clean(n.textContent) ||
        n.title ||
        n.id;
    return (
      <button
        key={n.id || i}
        title={n.title}
        disabled={n.matches(":disabled,.disabled")}
        onClick={() => {
          n.click();
          redraw();
        }}
      >
        <Icon size={15} />
        {label}
      </button>
    );
  };
  return (
    <div className="wb-designed-settings page-connection">
      <div ref={ref} className="wb-settings-source" aria-hidden="true" inert />
      <Notice error={error} />
      <header className="wb-designed-page-head">
        <div>
          <h2>服务与凭据</h2>
        </div>
      </header>
      <section className="wb-designed-section">
        <h3>地址与凭据</h3>
        <div className="wb-designed-fields">{controls.filter(isCredentialControl).map(renderControl)}</div>
        <div className="wb-designed-actions">{actions.filter(isCredentialAction).map(renderAction)}</div>
      </section>
      <Fold title="请求与高级参数">
        <div className="wb-designed-fields">
          {controls.filter((n) => !isCredentialControl(n)).map(renderControl)}
        </div>
        <div className="wb-designed-actions">
          {actions.filter((n) => !isCredentialAction(n)).map(renderAction)}
        </div>
      </Fold>
      {!controls.length && !actions.length && <p className="wb-note">当前没有可用配置。</p>}
    </div>
  );
}
