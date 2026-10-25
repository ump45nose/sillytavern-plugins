import { FileOutput, ListTree, ImagePlus } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { addons, addonEnabled } from "../addons/catalog";
import { Switch } from "../ui/ResourceControls";
import { useHostSlices } from "../ui/common";
import SyncStatus from "./SyncStatus";
export default function AddonSettings({ host }: { host: HostAdapter }) {
  useHostSlices(host, ["prefs"]);
  const prefs = host.prefs();
  // Board "SettingsAddons": one line of context, then a card per add-on with its switch in the corner.
  return (
    <section className="wb-addon-settings" aria-label="工作台附加功能">
      <p className="wb-addon-intro">
        附加功能随工作台一起发布：启用后点击入口才加载，关闭后入口移除、数据保留；写作和生图任务继续运行。
      </p>
      <div className="wb-addon-grid">
        {addons.map((addon) => {
          const enabled = addonEnabled(prefs, addon.id);
          const Icon = addon.id === "outline" ? ListTree : addon.id === "image-gen" ? ImagePlus : FileOutput;
          return (
            <article className={`wb-addon-card ${enabled ? "is-enabled" : ""}`} key={addon.id}>
              <header>
                <span className="wb-addon-icon" aria-hidden="true">
                  <Icon size={19} />
                </span>
                <strong>
                  {addon.label}
                  <small>v{addon.version}</small>
                </strong>
                <Switch
                  label={`启用${addon.label}`}
                  checked={enabled}
                  onChange={(value) => host.preference({ addons: { ...prefs.addons, [addon.id]: value } })}
                />
              </header>
              <p>{addon.description}</p>
              <footer>
                <span>{enabled ? "已启用 · 按需加载" : "未启用"}</span>
                <small>
                  {addon.id === "outline"
                    ? "入口：左栏大纲"
                    : addon.id === "image-gen"
                      ? "入口：正文铅笔旁 / 右栏"
                      : "入口：右栏分类 / 常用工具栏"}
                </small>
              </footer>
            </article>
          );
        })}
        <SyncStatus host={host} />
      </div>
    </section>
  );
}
