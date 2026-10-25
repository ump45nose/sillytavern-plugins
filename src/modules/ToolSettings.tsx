import { useState } from "react";
import { ArrowDown, ArrowUp, RotateCcw, Settings2, X } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { addonEnabled } from "../addons/catalog";
import { exportTool, pinnedTools, type PinnedTool } from "../host/tools";
import { Empty, SearchBox, useHostSlices } from "../ui/common";
import { toolIcon } from "../ui/ToolIcon";
import { useTools } from "../ui/useTools";
export default function ToolSettings({ host }: { host: HostAdapter }) {
  useHostSlices(host, ["prefs"]);
  useTools();
  const [query, setQuery] = useState("");
  const selected = pinnedTools(host.prefs().pinnedTools);
  const native = [...host.menuItems("menu"), ...host.menuItems("tools")].filter(
    (item) => item.node.id !== "attachFile",
  );
  const all = [
    { ...exportTool, pinnable: true, disabled: !addonEnabled(host.prefs(), "record-export") },
    ...native,
  ];
  const save = (value: PinnedTool[]) => host.preference({ pinnedTools: value });
  const move = (index: number, delta: number) => {
    const next = [...selected];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    save(next);
  };
  return (
    <section className="wb-tool-settings" aria-label="常用工具配置">
      <header className="wb-utility-heading">
        <div>
          <h3>常用工具</h3>
          <p>选定的入口显示在输入框工具栏，两个工作台共用。</p>
        </div>
        <button onClick={() => save([exportTool])}>
          <RotateCcw size={15} />
          恢复默认
        </button>
      </header>
      <div className="wb-tools-preview" aria-label="常用工具栏预览">
        <Settings2 size={16} />
        <small>工具栏</small>
        {selected.map((tool) => {
          const Icon = toolIcon(tool.id, tool.label);
          return (
            <span title={tool.label} key={tool.id}>
              <Icon size={17} />
            </span>
          );
        })}
        {!selected.length && <small>尚未添加常用入口</small>}
      </div>
      <div className="wb-tools-configuration">
        <section className="wb-tools-order">
          <h4>已选 · {selected.length}</h4>
          {selected.map((tool, index) => {
            const Icon = toolIcon(tool.id, tool.label),
              available = all.some(
                (t) => t.id === tool.id && t.pinnable && (t.id !== exportTool.id || !t.disabled),
              );
            return (
              <div className={`wb-tool-ordered ${available ? "" : "is-unavailable"}`} key={tool.id}>
                <Icon size={17} />
                <span>
                  {tool.label}
                  {!available && <small>当前不可用，入口仍为你保留</small>}
                </span>
                <button
                  className="wb-icon"
                  aria-label={`上移 ${tool.label}`}
                  disabled={!index}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp size={14} />
                </button>
                <button
                  className="wb-icon"
                  aria-label={`下移 ${tool.label}`}
                  disabled={index === selected.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown size={14} />
                </button>
                <button
                  className="wb-icon"
                  aria-label={`移除 ${tool.label}`}
                  onClick={() => save(selected.filter((t) => t.id !== tool.id))}
                >
                  <X size={14} />
                </button>
              </div>
            );
          })}
          {!selected.length && <Empty>从右侧选择常用工具</Empty>}
        </section>
        <section className="wb-tools-catalog">
          <SearchBox value={query} onChange={setQuery} placeholder="搜索工具名称" />
          <div className="wb-tools-grid">
            {all
              .filter((item) => item.label.toLowerCase().includes(query.toLowerCase()))
              .map((item, i) => {
                const Icon = toolIcon(item.id, item.label),
                  checked = selected.some((t) => t.id === item.id);
                return (
                  <label className={`wb-tool-choice ${checked ? "is-selected" : ""}`} key={`${item.id}:${i}`}>
                    <Icon size={19} />
                    <span>
                      {item.label}
                      <small>
                        {item.id === exportTool.id
                          ? item.disabled
                            ? "附加插件已停用，可在扩展中启用"
                            : "附加插件 · 按需加载"
                          : !item.pinnable
                            ? "同名入口无法固定"
                            : item.disabled
                              ? "当前暂不可执行"
                              : item.id.includes(":menu:")
                                ? "聊天工具"
                                : "扩展工具"}
                      </small>
                    </span>
                    <input
                      type="checkbox"
                      aria-label={`固定 ${item.label}`}
                      checked={checked}
                      disabled={!item.pinnable}
                      onChange={(event) =>
                        save(
                          event.target.checked
                            ? [...selected, { id: item.id, label: item.label }]
                            : selected.filter((t) => t.id !== item.id),
                        )
                      }
                    />
                  </label>
                );
              })}
          </div>
          {!all.some((item) => item.label.toLowerCase().includes(query.toLowerCase())) && (
            <Empty>没有匹配的工具</Empty>
          )}
        </section>
      </div>
    </section>
  );
}
