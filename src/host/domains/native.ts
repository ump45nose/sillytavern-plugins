import type { HostAdapter } from "../adapter";
import { nativeMenuItems } from "../tools";

/** Native controls: leasing settings DOM and clicking menu entries. */
export const nativeMethods = {
  click(this: HostAdapter, selector: string) {
    const nodes = [...document.querySelectorAll<HTMLElement>(selector)];
    const element =
      nodes.find((n) => !n.classList.contains("displayNone") && getComputedStyle(n).display !== "none") ??
      nodes[0];
    if (!element) throw new Error("当前酒馆未提供此入口。");
    element.click();
  },
  menuItems(this: HostAdapter, kind: "menu" | "tools") {
    return nativeMenuItems(kind);
  },
  /** Lease original controls with their handlers intact; every lease restores its exact origin. */
  leaseNative(this: HostAdapter, id: string, container: HTMLElement) {
    const node = document.getElementById(id);
    if (!node) throw new Error(`酒馆未提供 ${id} 控件。`);
    if (node.closest(".wb-native-settings-slot")) throw new Error("此设置已在其他编辑区打开。");
    return this.lease(node, container, "Workbench native settings origin");
  },
};
