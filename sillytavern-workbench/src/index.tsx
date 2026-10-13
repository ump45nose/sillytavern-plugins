import React from "react";
import { createRoot, Root } from "react-dom/client";
import { HostAdapter, nativeNodes } from "./host/adapter";
import {disposeAddons} from "./addons/runtime";
import App, { beforeClose } from "./App";
import { LayoutSwitcher, type LayoutMode } from "./ui/LayoutSwitcher";
import { createTrace } from "../extension/trace.js";
import "./style.css";
import "./home.css";
import "./controls.css";
import "./resources.css";
import "./workspace.css";
import "./rework.css";
import "./polish.css";
import "./selection.css";
import "./preferences.css";
import "./rp.css";
import "./layout.css";
import "./utility.css";
import "./addon-shell.css";
import "./mobile.css";
class Boundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    console.error("[Workbench] render failed", error);
    queueMicrotask(unmount);
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}
const context = window.SillyTavern?.getContext?.();
const metrics: Record<string, number> = {
  extensionLoadedMs: performance.now(),
};
window.workbenchStartup?.mark("extensionLoadedMs", metrics.extensionLoadedMs);
let root: Root | undefined,
  container: HTMLElement | undefined,
  toolbar: HTMLElement | undefined,
  host: HostAdapter | undefined,
  trace: ReturnType<typeof createTrace> | undefined;
let mounted = false,
  mounting = false,
  disposed = false;
let layoutRoot:Root | undefined, layoutContainer:HTMLElement | undefined, unsubscribeLayout:(()=>void) | undefined;
const launcher = document.createElement("button");
launcher.id = "wb-launcher";
launcher.textContent = "创作工作台";
function updateLayoutSwitcher() {
  if (!layoutRoot || disposed) return;
  const mode:LayoutMode = mounted ? host?.prefs().layout === "rp" ? "rp" : "novel" : "native";
  layoutRoot.render(<LayoutSwitcher mode={mode} onChange={changeLayout}/>);
}
async function changeLayout(mode:LayoutMode) {
  if (!beforeClose()) return false;
  if (mode === "native") {
    const previous = context.accountStorage.getItem("wb-native");
    context.accountStorage.setItem("wb-native", "true");
    try {
      if (host) await host.persistSettings();
      else { const scriptPath = "/script.js"; await (await import(scriptPath)).saveSettings(); }
    } catch (error) {
      if (previous === null) context.accountStorage.removeItem("wb-native");
      else context.accountStorage.setItem("wb-native", previous);
      throw error;
    }
    unmount();
    return true;
  }
  if (window.storyWorkspace) throw new Error("请先停用 Story Workspace，再切换工作台。");
  context.accountStorage.removeItem("wb-native");
  if (!mounted) {
    context.extensionSettings.workbench ??= {};
    context.extensionSettings.workbench.layout = mode;
    await mount();
  } else host!.preference({ layout:mode });
  if (!mounted || !host) throw new Error("工作台未能载入，请刷新后重试。");
  await host.persistSettings();
  updateLayoutSwitcher();
  return true;
}
async function mount() {
  if (mounted || mounting || disposed) return;
  if (window.storyWorkspace) {
    launcher.textContent = "请先停用 Story Workspace";
    return;
  }
  if (!nativeNodes.chat || !nativeNodes.input) return;
  mounting = true;
  try {
    host = new HostAdapter();
    await host.init();
    unsubscribeLayout = host.subscribe(updateLayoutSwitcher);
    if (disposed) {
      host.destroy();
      return;
    }
    trace = createTrace(context, window, () => host?.traceComposition());
    container = document.createElement("div");
    container.id = "wb-root";
    container.className = "wb-ui";
    document.body.append(container);
    toolbar = document.createElement("div");
    toolbar.className = "wb-composer-tools wb-ui";
    document.querySelector("#nonQRFormItems")!.append(toolbar);
    root = createRoot(container);
    root.render(
      <Boundary>
        <App
          host={host}
          trace={trace}
          toolbar={toolbar}
          onExit={() => {
            void changeLayout("native").catch(error => host?.report(error));
          }}
          onLayout={mode => { void changeLayout(mode).catch(error => host?.report(error)); }}
        />
      </Boundary>,
    );
    document.body.classList.add("wb-active");
    launcher.hidden = true;
    mounted = true;
    updateLayoutSwitcher();
    metrics.mountedMs = performance.now();
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        if (mounted && document.querySelector(".wb-top,.wb-mobile-header")) {
          metrics.workbenchReadyMs = performance.now();
          window.workbenchStartup?.mark("workbenchReadyMs", metrics.workbenchReadyMs);
        }
      }),
    );
  } catch (error) {
    console.error("[Workbench] mount failed", error);
    unmount();
    launcher.textContent = "工作台载入失败 · 重试";
  } finally {
    mounting = false;
  }
}
function unmount() {
  unsubscribeLayout?.(); unsubscribeLayout = undefined;
  root?.unmount();
  root = undefined;
  if(host)disposeAddons(host);
  host?.destroy();
  host = undefined;
  trace?.destroy();
  trace = undefined;
  container?.remove();
  toolbar?.remove();
  container = undefined;
  toolbar = undefined;
  document.body.classList.remove(
    "wb-active",
    "wb-mobile",
    "wb-mobile-rp",
    "wb-mobile-editor",
    "wb-mobile-tools",
    "wb-mobile-lowered",
    "wb-mobile-keyboard",
    "wb-mobile-dragging",
    "wb-mobile-busy",
    "wb-mobile-offline",
    "wb-left-open",
    "wb-left-hover-open",
    "wb-right-hover-open",
    "wb-right-open",
    "wb-rail-open",
    "wb-focus",
    "wb-resizing",
    "wb-native-panel",
    "wb-rp",
    "wb-rp-top-auto",
    "wb-rp-top-collapsed",
    "wb-rp-overlay-open",
  );
  mounted = false;
  launcher.hidden = !!layoutRoot;
  updateLayoutSwitcher();
}
launcher.addEventListener("click", () => {
  context.accountStorage.removeItem("wb-native");
  void mount();
});
function start() {
  document.body.append(launcher);
  layoutContainer = document.createElement("div");
  layoutContainer.id = "wb-layout-root";
  document.body.append(layoutContainer);
  layoutRoot = createRoot(layoutContainer);
  launcher.hidden = true;
  updateLayoutSwitcher();
  if (context.accountStorage.getItem("wb-native") !== "true") void mount();
}
function ready() {
  metrics.appReadyMs = performance.now();
  start();
}
context.eventSource.on(context.eventTypes.APP_READY, ready);
context.eventSource.on(context.eventTypes.APP_INITIALIZED, initialized);
function initialized() {
  metrics.appInitializedMs = performance.now();
}
window.workbench = {
  mount,
  unmount,
  metrics,
  nativeNodes,
  get mounted() {
    return mounted;
  },
  get host() {
    return host;
  },
  get records() {
    return trace?.records ?? [];
  },
  clear: () => trace?.clear(),
  capabilities: () => ({
    context: true,
    nativeChat: !!nativeNodes.chat?.isConnected,
    nativeInput: !!nativeNodes.input?.isConnected,
    helper: typeof (window as any).TavernHelper?.getChatMessages === "function",
  }),
};
// Keep the verified diagnostics interface available for regression tooling.
window.workbenchProbe = window.workbench;
window.addEventListener(
  "pagehide",
  () => {
    disposed = true;
    unmount();
    layoutRoot?.unmount(); layoutRoot = undefined;
    layoutContainer?.remove(); layoutContainer = undefined;
    launcher.remove();
    context.eventSource.removeListener(context.eventTypes.APP_READY, ready);
    context.eventSource.removeListener(
      context.eventTypes.APP_INITIALIZED,
      initialized,
    );
  },
  { once: true },
);
