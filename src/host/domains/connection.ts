import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, mergeEdits } from "../model";
import { ctx } from "../internals";

/** Connection profiles and the mirrored quick API controls (non-secret fields only). */
export const connectionMethods = {
  /** Only non-secret fields are mirrored into the quick API controls. */
  connectionControls(this: HostAdapter) {
    const main = document.getElementById("main_api") as HTMLSelectElement;
    const api = main?.value || "openai";
    const provider = document.getElementById(
      api === "openai" ? "chat_completion_source" : "textgen_type",
    ) as HTMLSelectElement;
    const source = provider?.value || "";
    const control = (node: HTMLSelectElement | HTMLInputElement | null) =>
      node
        ? {
            id: node.id,
            value: node.value,
            disabled: node.disabled,
            type: node instanceof HTMLSelectElement ? "select" : "text",
            options:
              node instanceof HTMLSelectElement
                ? [...node.options].map((o) => ({
                    value: o.value,
                    label: o.textContent || o.value,
                    disabled: o.disabled,
                  }))
                : [],
          }
        : null;
    let model: HTMLSelectElement | HTMLInputElement | null = null,
      // Sources with a free model ID also list the models the endpoint reported; choosing one fills the ID.
      pick: HTMLSelectElement | null = null;
    const root = document.getElementById(
      api === "openai"
        ? "openai_api"
        : api === "textgenerationwebui"
          ? "textgenerationwebui_api"
          : "rm_api_block",
    );
    if (api === "openai" && source === "custom") {
      model = document.getElementById("custom_model_id") as HTMLInputElement;
      pick = document.getElementById("model_custom_select") as HTMLSelectElement;
    } else if (api === "textgenerationwebui" && source === "generic") {
      model = document.getElementById("generic_model_textgenerationwebui") as HTMLInputElement;
      pick = document.getElementById("generic_model_select") as HTMLSelectElement;
    } else if (api === "novel") model = document.getElementById("model_novel_select") as HTMLSelectElement;
    else if (api === "openai" || api === "textgenerationwebui") {
      model =
        [...(root?.querySelectorAll<HTMLSelectElement>("select") || [])].find((n) => {
          const scope = n.closest<HTMLElement>(api === "openai" ? "[data-source]" : "[data-tg-type]");
          return (
            /^(model_.+_select|azure_openai_model|openrouter_model|mancer_model|vllm_model|aphrodite_model|llamacpp_model|ollama_model|tabby_model)$/.test(
              n.id,
            ) &&
            !n.multiple &&
            !!scope &&
            (scope.dataset[api === "openai" ? "source" : "tgType"] || "").split(/,\s*/).includes(source)
          );
        }) || null;
    }
    const connect = (
      {
        openai: "api_button_openai",
        textgenerationwebui: "api_button_textgenerationwebui",
        novel: "api_button_novel",
        kobold: "api_button",
        koboldhorde: "horde_api_key_button",
      } as Record<string, string>
    )[api];
    const loading = document
      .querySelector<HTMLElement>(`#${connect}`)
      ?.parentElement?.querySelector<HTMLElement>(".api_loading");
    return {
      main: control(main)!,
      provider: api === "openai" || api === "textgenerationwebui" ? control(provider) : null,
      model: control(model),
      pick: pick && [...pick.options].some((o) => o.value) ? control(pick) : null,
      connect,
      test: api === "openai" ? "test_api_button" : null,
      connecting: !!loading && getComputedStyle(loading).display !== "none",
    };
  },
  setConnectionControl(this: HostAdapter, id: string, value: string) {
    const allowed = this.connectionControls();
    if (![allowed.main, allowed.provider, allowed.model, allowed.pick].some((x) => x?.id === id))
      throw new Error("当前连接不支持此字段");
    const node = document.getElementById(id) as HTMLSelectElement | HTMLInputElement;
    node.value = value;
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
    this.invalidate("session");
  },
  /** Puts API, provider and model back to an earlier `connectionControls()` reading, e.g. after a preset switch moved them. */
  restoreConnectionControls(
    this: HostAdapter,
    state: Record<"main" | "provider" | "model", { id: string; value: string } | null>,
  ) {
    for (const control of [state.main, state.provider, state.model]) {
      if (!control) continue;
      const node = document.getElementById(control.id) as HTMLInputElement | HTMLSelectElement | null;
      if (node && node.value !== control.value) this.setConnectionControl(control.id, control.value);
    }
  },
  watchConnectionControls(this: HostAdapter, callback: () => void) {
    const node = document.getElementById("rm_api_block");
    if (!node) return () => {};
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(callback);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(node, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["style", "disabled"],
    });
    node.addEventListener("change", schedule);
    node.addEventListener("input", schedule);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      node.removeEventListener("change", schedule);
      node.removeEventListener("input", schedule);
    };
  },
  decorateConnectionControls(this: HostAdapter) {
    const state = this.connectionControls(),
      marked: HTMLElement[] = [];
    for (const field of [state.main, state.provider, state.model, state.pick]) {
      const node = field && document.getElementById(field.id);
      if (!node) continue;
      const heading = node.previousElementSibling?.matches("h4")
        ? node.previousElementSibling
        : node.parentElement?.previousElementSibling?.matches("h4")
          ? node.parentElement.previousElementSibling
          : null;
      for (const target of [node, heading])
        if (target instanceof HTMLElement && !target.classList.contains("wb-connection-bridged")) {
          target.classList.add("wb-connection-bridged");
          marked.push(target);
        }
    }
    const actions = document.querySelector<HTMLElement>(`#${state.connect}`)?.parentElement;
    if (
      actions &&
      actions.querySelector(".api_loading") &&
      !actions.classList.contains("wb-connection-actions-original")
    ) {
      actions.classList.add("wb-connection-actions-original");
      marked.push(actions);
    }
    const profiles = document.getElementById("connection_profiles")?.parentElement?.parentElement;
    if (
      profiles?.querySelector("#create_connection_profile") &&
      !profiles.classList.contains("wb-connection-profile-original")
    ) {
      profiles.classList.add("wb-connection-profile-original");
      marked.push(profiles);
    }
    return () =>
      marked.forEach((n) =>
        n.classList.remove(
          "wb-connection-bridged",
          "wb-connection-actions-original",
          "wb-connection-profile-original",
        ),
      );
  },
  async saveProfile(this: HostAdapter, id: string, base: Data, patch: Data) {
    const cm = ctx().extensionSettings.connectionManager,
      profile = cm.profiles.find((x: Data) => x.id === id);
    if (!profile) throw new Error("连接已删除。");
    patch.name = String(patch.name ?? "").trim();
    if (!patch.name || cm.profiles.some((p: Data) => p.id !== id && p.name === patch.name))
      throw new Error("连接名称不能为空或与其他连接重复。");
    const previous = clone(profile),
      next = mergeEdits(base, { ...base, ...patch }, profile);
    Object.assign(profile, next);
    try {
      await this.persistSettings();
    } catch (error) {
      for (const key of Object.keys(patch)) if (profile[key] === next[key]) profile[key] = previous[key];
      this.invalidate("resources");
      throw error;
    }
    const option = [...document.querySelectorAll<HTMLOptionElement>("#connection_profiles option")].find(
      (x) => x.value === id,
    );
    if (option) option.textContent = profile.name;
    await ctx().eventSource.emit(ctx().eventTypes.CONNECTION_PROFILE_UPDATED, profile);
  },
};
