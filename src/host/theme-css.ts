/** Pause the native theme CSS without changing the user's saved theme or editor content. */
export function suspendThemeCss() {
  const themes = document.querySelector<HTMLSelectElement>("#themes");
  const selection = themes?.value;
  const disabled = themes?.disabled;
  const paused = new Option("工作台外观（原生主题已停用）", "__wb_theme_paused__");
  if (themes) {
    themes.append(paused);
    themes.value = paused.value;
    themes.disabled = true;
  }
  const controls = ["UI-presets-block", "CustomCSS-block"].flatMap((id) => {
    const node = document.getElementById(id);
    if (!node) return [];
    const inert = node.inert;
    node.inert = true;
    return [{ node, inert }];
  });
  const notice = document.createElement("small");
  notice.textContent = "原生主题与自定义 CSS 已暂停，切回原生界面后恢复。";
  document.getElementById("UI-presets-block")?.after(notice);
  const styles = new Map<HTMLStyleElement, string | null>();
  const suspend = () => {
    const style = document.querySelector<HTMLStyleElement>("style#custom-style");
    if (!style) return;
    if (!styles.has(style)) styles.set(style, style.getAttribute("media"));
    style.media = "not all";
  };
  suspend();
  // Native theme selection and CSS editing can rewrite or recreate this style while mounted.
  const observer = new MutationObserver(suspend);
  observer.observe(document.head, { childList: true, subtree: true });
  return () => {
    observer.disconnect();
    notice.remove();
    paused.remove();
    if (themes) {
      themes.value = selection!;
      themes.disabled = disabled!;
    }
    for (const { node, inert } of controls) node.inert = inert;
    for (const [style, media] of styles) {
      if (media === null) style.removeAttribute("media");
      else style.setAttribute("media", media);
    }
  };
}
