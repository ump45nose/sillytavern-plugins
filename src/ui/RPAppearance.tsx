import React, { useState } from "react";
import { Type } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { useHost } from "./common";
import { Popover } from "./Popover";
import { usePresence } from "./Motion";
import { boundedPreference } from "../host/rp";

export function RPAppearance({ host }: { host: HostAdapter }) {
  useHost(host);
  const prefs = host.prefs(), [anchor, setAnchor] = useState<HTMLElement | null>(null), presence = usePresence(anchor);
  return <><button className="wb-icon" title="RP 外观" aria-label="RP 外观" aria-expanded={!!anchor} onClick={e => setAnchor(anchor ? null : e.currentTarget)}><Type size={17} /></button>
    {presence.value && <Popover anchor={presence.value} title="RP 外观" exiting={presence.exiting} onClose={() => setAnchor(null)}><div className="wb-pop-form">
      <span className="wb-pop-label">对白字体</span><div className="wb-font-choices">{[["serif", "宋体 · 纸书"], ["sans", "黑体 · 清晰"]].map(([value, label]) => <button key={value} aria-pressed={(prefs.readingFont || "serif") === value} onClick={() => host.preference({ readingFont: value as "serif" | "sans" })}>{label}</button>)}</div>
      <label className="wb-field"><span>对白字号<output>{boundedPreference(prefs.rpTextSize, 19, 14, 26)} px</output></span><input aria-label="RP 对白字号" type="range" min="14" max="26" value={boundedPreference(prefs.rpTextSize, 19, 14, 26)} onChange={e => host.preference({ rpTextSize: Number(e.target.value) })} /></label>
      <label className="wb-field"><span>对白区域宽度<output>{boundedPreference(prefs.rpDialogWidth, 88, 65, 94)}%</output></span><input aria-label="RP 对白宽度" type="range" min="65" max="94" value={boundedPreference(prefs.rpDialogWidth, 88, 65, 94)} onChange={e => host.preference({ rpDialogWidth: Number(e.target.value) })} /></label>
      <label className="wb-field"><span>角色立绘大小<output>{boundedPreference(prefs.rpSpriteScale, 91, 55, 100)}%</output></span><input aria-label="RP 立绘大小" type="range" min="55" max="100" value={boundedPreference(prefs.rpSpriteScale, 91, 55, 100)} onChange={e => host.preference({ rpSpriteScale: Number(e.target.value) })} /></label>
      <label className="wb-check"><input type="checkbox" checked={!!prefs.rpTopAuto} onChange={e => host.preference({ rpTopAuto: e.target.checked })} />鼠标悬浮显示顶栏</label>
      <label className="wb-check"><input type="checkbox" checked={prefs.rpShowPortraits !== false} onChange={e => host.preference({ rpShowPortraits: e.target.checked })} />没有立绘时显示角色画像</label>
    </div></Popover>}
  </>;
}
