import type { HostAdapter } from "../host/adapter";
import NativeSettings from "./NativeSettings";
import { InstalledExtensions, ReadingForm } from "./DesignedSettings";
import { bus } from "../host/bus";
/** Lease whole native components. Their lists, local actions and dynamic editors remain owned by the host. */
export default function ComponentSettings({
  host,
  page,
  group,
  extensionId,
}: {
  host: HostAdapter;
  page: string;
  group: string;
  extensionId?: string;
}) {
  const installed = page === "extensions" && group === "已安装";
  return (
    <section className={`wb-component-settings page-${page}`} aria-label={group}>
      {page === "settings" && group === "外观与阅读" && <ReadingForm host={host} />}
      {installed ? (
        <InstalledExtensions
          host={host}
          open={(id) => bus.emit("settings-group", { group: "扩展设置", extension: id })}
        />
      ) : page === "settings" && group === "外观与阅读" ? (
        <section className="wb-reading-native" aria-label="SillyTavern 外观">
          <h3>SillyTavern 外观</h3>
          <NativeSettings host={host} page={page} group={group} extensionId={extensionId} />
        </section>
      ) : (
        <NativeSettings host={host} page={page} group={group} extensionId={extensionId} />
      )}
    </section>
  );
}
