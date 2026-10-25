import { lazy, type ComponentType } from "react";
import { RotateCw } from "./icons";

/**
 * Every build replaces the hashed chunks, so a page opened before an update asks for chunks that
 * no longer exist. Without this, the rejected import reaches the root boundary, which unmounts the
 * workbench and leaves the native UI behind. Render a reload prompt in place of the chunk instead.
 */
export function lazyChunk<P extends object>(load: () => Promise<{ default: ComponentType<P> }>) {
  return lazy(() =>
    load().catch((error) => {
      console.warn("[Workbench] chunk failed to load; the extension was probably updated", error);
      return { default: StaleChunk as ComponentType<P> };
    }),
  );
}

function StaleChunk() {
  return (
    <div className="wb-stale-chunk" role="alert">
      <span>工作台已更新，刷新页面后可继续使用</span>
      <button type="button" onClick={() => location.reload()}>
        <RotateCw size={14} />
        刷新
      </button>
    </div>
  );
}
