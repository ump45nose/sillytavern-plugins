import { useState } from "react";
import { ChevronLeft, Type } from "./icons";
import type { HostAdapter } from "../host/adapter";
import { useHostSlices } from "./common";
import { Popover } from "./Popover";
import { usePresence } from "./Motion";
import { boundedPreference } from "../host/rp";
import { CastPanel, CastSource } from "./RPCast";

export function RPAppearance({
  host,
  openPortraits,
}: {
  host: HostAdapter;
  /** Opens a world-book entry at its portraits. */
  openPortraits: (book: string, title: string) => void;
}) {
  useHostSlices(host, ["prefs"]);
  const prefs = host.prefs(),
    [anchor, setAnchor] = useState<HTMLElement | null>(null),
    [view, setView] = useState<"appearance" | "cast">("appearance"),
    presence = usePresence(anchor);
  const close = () => {
    setAnchor(null);
    setView("appearance");
  };
  return (
    <>
      <button
        className="wb-rp-tool"
        title="RP 外观"
        aria-label="RP 外观"
        aria-expanded={!!anchor}
        onClick={(e) => (anchor ? close() : setAnchor(e.currentTarget))}
      >
        <Type size={16} />
      </button>
      {presence.value && (
        <Popover
          anchor={presence.value}
          title={view === "cast" ? "立绘阵容" : "RP 外观"}
          className={view === "cast" ? "is-wide" : ""}
          tools={
            view === "cast" && (
              <button onClick={() => setView("appearance")}>
                <ChevronLeft size={13} aria-hidden="true" />
                外观
              </button>
            )
          }
          exiting={presence.exiting}
          onClose={close}
        >
          {view === "cast" ? (
            <CastPanel
              host={host}
              onManage={(book, title) => {
                close();
                openPortraits(book, title);
              }}
            />
          ) : (
            <div className="wb-pop-form">
              <span className="wb-pop-label">对白字体</span>
              <div className="wb-font-choices">
                {[
                  ["serif", "宋体 · 纸书"],
                  ["sans", "黑体 · 清晰"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    aria-pressed={(prefs.readingFont || "serif") === value}
                    onClick={() => host.preference({ readingFont: value as "serif" | "sans" })}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <label className="wb-field">
                <span>
                  对白字号<output>{boundedPreference(prefs.rpTextSize, 19, 14, 26)} px</output>
                </span>
                <input
                  aria-label="RP 对白字号"
                  type="range"
                  min="14"
                  max="26"
                  value={boundedPreference(prefs.rpTextSize, 19, 14, 26)}
                  onChange={(e) => host.preference({ rpTextSize: Number(e.target.value) })}
                />
              </label>
              <label className="wb-field">
                <span>
                  对白区域宽度<output>{boundedPreference(prefs.rpDialogWidth, 72, 65, 94)}%</output>
                </span>
                <input
                  aria-label="RP 对白宽度"
                  type="range"
                  min="65"
                  max="94"
                  value={boundedPreference(prefs.rpDialogWidth, 72, 65, 94)}
                  onChange={(e) => host.preference({ rpDialogWidth: Number(e.target.value) })}
                />
              </label>
              <label className="wb-field">
                <span>
                  角色立绘大小<output>{boundedPreference(prefs.rpSpriteScale, 91, 55, 100)}%</output>
                </span>
                <input
                  aria-label="RP 立绘大小"
                  type="range"
                  min="55"
                  max="100"
                  value={boundedPreference(prefs.rpSpriteScale, 91, 55, 100)}
                  onChange={(e) => host.preference({ rpSpriteScale: Number(e.target.value) })}
                />
              </label>
              <label className="wb-check">
                <input
                  type="checkbox"
                  checked={prefs.rpTopAuto !== false}
                  onChange={(e) => host.preference({ rpTopAuto: e.target.checked })}
                />
                鼠标悬浮显示顶栏
              </label>
              <label className="wb-check">
                <input
                  type="checkbox"
                  checked={prefs.rpShowPortraits !== false}
                  onChange={(e) => host.preference({ rpShowPortraits: e.target.checked })}
                />
                没有立绘时显示角色画像
              </label>
              <CastSource host={host} onOpen={() => setView("cast")} />
            </div>
          )}
        </Popover>
      )}
    </>
  );
}
