import { useLayoutEffect } from "react";

/** Follow the visible viewport, including a software keyboard, without replacing native input. */
export function useMobileViewport(active: boolean) {
  useLayoutEffect(() => {
    if (!active) return;
    const viewport = window.visualViewport;
    let frame = 0;
    const apply = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        document.body.style.setProperty("--wb-mobile-height", `${viewport?.height ?? innerHeight}px`);
        document.body.style.setProperty("--wb-mobile-top", `${viewport?.offsetTop ?? 0}px`);
        const focused = document.activeElement;
        const typing =
          focused instanceof HTMLInputElement ||
          focused instanceof HTMLTextAreaElement ||
          (focused instanceof HTMLElement && focused.isContentEditable);
        document.body.classList.toggle(
          "wb-mobile-keyboard",
          typing && !!viewport && innerHeight - viewport.height > 140,
        );
      });
    };
    const theme = document.querySelector<HTMLMetaElement>("meta[name=theme-color]"),
      themeBefore = theme?.content;
    if (theme) theme.content = getComputedStyle(document.body).backgroundColor;
    apply();
    document.addEventListener("focusin", apply);
    document.addEventListener("focusout", apply);
    viewport?.addEventListener("resize", apply);
    viewport?.addEventListener("scroll", apply);
    window.addEventListener("resize", apply);
    const meta = document.querySelector<HTMLMetaElement>("meta[name=viewport]"),
      previous = meta?.content;
    if (meta && !meta.content.includes("viewport-fit")) meta.content += ", viewport-fit=cover";
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("focusin", apply);
      document.removeEventListener("focusout", apply);
      if (theme && themeBefore !== undefined) theme.content = themeBefore;
      viewport?.removeEventListener("resize", apply);
      viewport?.removeEventListener("scroll", apply);
      window.removeEventListener("resize", apply);
      document.body.style.removeProperty("--wb-mobile-height");
      document.body.style.removeProperty("--wb-mobile-top");
      document.body.classList.remove("wb-mobile-keyboard");
      if (meta && previous !== undefined) meta.content = previous;
    };
  }, [active]);
}
