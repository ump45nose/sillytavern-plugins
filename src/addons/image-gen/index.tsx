import { useEffect, useState, useSyncExternalStore } from "react";
import {
  ChevronRight,
  ImagePlus,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Upload,
  WandSparkles,
} from "../../ui/icons";
import References from "./References";
import type { AddonViewProps } from "../types";
import { Check } from "../../ui/ResourceControls";
import { configuration, defaultModels, providers, type ImageConfig, type Provider } from "./backends";
import { createRuntime, type ImageResult } from "./runtime";
import "./style.css";
export { createRuntime };
export const apiVersion = 2,
  id = "image-gen";
const names: Record<Provider, string> = {
  openai: "OpenAI 兼容",
  gemini: "Gemini",
  novelai: "NovelAI",
  a1111: "A1111",
  comfyui: "ComfyUI",
};
export function Workspace({ host, runtime, editor }: AddonViewProps) {
  useSyncExternalStore(runtime.subscribe, runtime.revision);
  const state = runtime.state(),
    task = runtime.task(),
    [error, setError] = useState(""),
    [config, setConfig] = useState<ImageConfig>(configuration(host.config())),
    [saved, setSaved] = useState("");
  const run = (name: string, ...args: any[]) => {
    setError("");
    return runtime.action(name, ...args).catch((e) => setError(e.message));
  };
  const messages = host.exportSnapshot().messages;
  useEffect(() => {
    if (!state.target && messages.length) void run("target", host.target(messages.at(-1)!.id));
  }, []);
  const field = (key: keyof ImageConfig, label: string, type = "text") => (
    <label key={key}>
      {label}
      <input
        aria-label={label}
        type={type}
        min={key === "referenceStrength" ? 0.01 : undefined}
        max={key === "referenceStrength" ? 1 : undefined}
        step={key === "referenceStrength" ? 0.01 : undefined}
        value={String(config[key])}
        autoComplete="off"
        onChange={(e) => {
          setSaved("");
          setConfig({ ...config, [key]: type === "number" ? Number(e.target.value) : e.target.value });
        }}
      />
    </label>
  );
  return (
    <section
      className={`wb-image-workspace wb-addon-view ${editor ? "is-editor" : ""}`}
      aria-label={editor ? "生图完整配置" : "生图工作区"}
    >
      <header className="wb-addon-heading">
        <strong>
          <ImagePlus size={17} />
          生图 <small>{names[config.provider]}</small>
        </strong>
        <div>
          <button aria-label="生图完整配置" onClick={() => host.open("editor")}>
            <SlidersHorizontal size={16} />
          </button>
          <button disabled={task.status !== "running"} onClick={() => run("stop")}>
            <Square size={14} />
            取消
          </button>
        </div>
      </header>
      {editor ? (
        <>
          <div className="wb-image-config-grid">
            <label>
              后端
              <select
                aria-label="生图后端"
                value={config.provider}
                onChange={(e) => {
                  const provider = e.target.value as Provider;
                  setConfig({ ...config, provider, model: defaultModels[provider], url: "" });
                  setSaved("");
                }}
              >
                {providers.map((provider) => (
                  <option key={provider} value={provider}>
                    {names[provider]}
                  </option>
                ))}
              </select>
            </label>
            {field("model", "模型 / Checkpoint")}
            {field("width", "宽度", "number")}
            {field("height", "高度", "number")}
            {field("steps", "步数", "number")}
            {field("scale", "引导强度", "number")}
            {field("seed", "种子 · -1 随机", "number")}
            {field("timeout", "超时 · 秒", "number")}
            {field("referenceStrength", "底图重绘幅度 · 0 到 1", "number")}
            {field("sampler", "采样器")}
            {field("scheduler", "调度器")}
            <label>
              转写格式
              <select
                value={config.style}
                onChange={(e) => setConfig({ ...config, style: e.target.value as "tags" | "natural" })}
              >
                <option value="natural">自然语言</option>
                <option value="tags">标签式</option>
              </select>
            </label>
            {field("before", "前文楼层数", "number")}
            <label className="span-two">
              后端地址
              <input
                aria-label="生图后端地址"
                value={config.url}
                onChange={(e) => setConfig({ ...config, url: e.target.value })}
                placeholder="http://… 或 https://…"
              />
            </label>
            <label className="span-two">
              API 密钥
              <input
                aria-label="生图 API 密钥"
                type="password"
                value={config.key}
                autoComplete="off"
                onChange={(e) => setConfig({ ...config, key: e.target.value })}
                placeholder="OpenAI / NovelAI 留空时使用酒馆已保存密钥"
              />
            </label>
            <label className="span-two">
              独立转写连接
              <select
                aria-label="转写连接"
                value={config.profile}
                onChange={(e) => setConfig({ ...config, profile: e.target.value })}
              >
                <option value="">当前连接配置</option>
                {host.profiles().map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="span-all">
              独立转写模板
              <textarea
                aria-label="独立转写模板"
                rows={5}
                value={config.template}
                onChange={(e) => setConfig({ ...config, template: e.target.value })}
              />
              <small>
                使用 {"{{scene}}"} 引入场景、{"{{style}}"} 引入输出格式。
              </small>
            </label>
            {config.provider === "comfyui" && (
              <label className="span-all">
                ComfyUI API 工作流
                <textarea
                  aria-label="ComfyUI 工作流"
                  rows={8}
                  value={config.workflow}
                  onChange={(e) => setConfig({ ...config, workflow: e.target.value })}
                  placeholder="留空使用默认工作流；或粘贴 API 格式 JSON"
                />
                <small>
                  支持 QIG 占位符：prompt / negative / seed / width / height / steps / cfg / reference_image。
                </small>
              </label>
            )}
          </div>
          <div className="wb-addon-actions">
            <button
              className="wb-primary"
              onClick={async () => {
                setError("");
                try {
                  await runtime.action("config", config);
                  setConfig(configuration(host.config()));
                  setSaved("配置已保存");
                } catch (error) {
                  setSaved("");
                  setError((error as Error).message);
                }
              }}
            >
              保存生图配置
            </button>
            <span>{saved}</span>
          </div>
          <p className="wb-addon-hint">
            自定义后端直接从浏览器请求，需要允许当前酒馆来源的
            CORS。密钥仅保存在用户配置，聊天元数据不包含密钥。
          </p>
        </>
      ) : (
        <>
          <div className="wb-image-target">
            <label>
              <span>目标楼层</span>
              <select
                aria-label="生图目标楼层"
                value={state.target?.id ?? ""}
                onChange={(e) => run("target", host.target(Number(e.target.value)))}
              >
                {messages.map((m) => (
                  <option key={m.id} value={m.id}>
                    #{m.id + 1} · {m.name} · {m.text.replace(/<[^>]*>/g, "").slice(0, 30)}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => run("manual", state.target)}
              disabled={!state.target || task.status === "running"}
            >
              <ImagePlus size={15} />
              输入提示词
            </button>
          </div>
          <References runtime={runtime} />
          <details className="wb-image-source">
            <summary>
              <ChevronRight size={14} />
              场景来源 · 已排除思考块
            </summary>
            <p>{state.source || "请选择目标楼层"}</p>
          </details>
          <label className="wb-image-prompt">
            <span>正面提示词</span>
            <textarea
              aria-label="生图正面提示词"
              rows={4}
              value={state.positive}
              onChange={(e) => run("patch", { positive: e.target.value })}
              placeholder="仅转写后可在此修改，或直接填写…"
            />
          </label>
          <label className="wb-image-prompt is-negative">
            <span>负面提示词</span>
            <textarea
              aria-label="生图负面提示词"
              rows={2}
              value={state.negative}
              onChange={(e) => run("patch", { negative: e.target.value })}
            />
          </label>
          <div className="wb-addon-actions wb-image-actions">
            <button disabled={task.status === "running" || !state.target} onClick={() => run("rewrite")}>
              <WandSparkles size={14} />
              仅转写
            </button>
            <button disabled={task.status === "running" || !state.positive} onClick={() => run("generate")}>
              <ImagePlus size={14} />
              生成
            </button>
            <span className="wb-grow" />
            <button
              className="wb-primary"
              disabled={task.status === "running" || !state.target}
              onClick={() => run("rewrite-generate")}
            >
              <Sparkles size={14} />
              转写并生成
            </button>
          </div>
          <div className="wb-image-results">
            {(state.results as ImageResult[]).map((result) => (
              <article key={result.id} className={result.attached ? "is-attached" : ""}>
                <img
                  src={result.url}
                  alt={result.positive.slice(0, 100)}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      "application/x-wb-image",
                      JSON.stringify({ id: result.id, url: result.url }),
                    );
                    e.dataTransfer.effectAllowed = "copy";
                  }}
                />
                <small className="wb-image-result-state">
                  {result.attached ? "已插入" : "待选"} · {result.target.id + 1} 层
                </small>
                <footer>
                  <button
                    title="插入当前目标楼层"
                    aria-label="插入图片"
                    onClick={() => run("insert", result.id, state.target)}
                  >
                    <Upload size={13} />
                  </button>
                  <button
                    title="重新生成并替换"
                    aria-label="重新生成图片"
                    disabled={task.status === "running"}
                    onClick={() => run("regenerate", result.id)}
                  >
                    <RotateCcw size={13} />
                  </button>
                  <button title="移除图片附件" aria-label="移除图片" onClick={() => run("remove", result.id)}>
                    <Trash2 size={13} />
                  </button>
                </footer>
              </article>
            ))}
            {task.status === "running" && (
              <div className="wb-image-pending" role="presentation">
                <span>{task.label || "生成中"}</span>
                <i />
              </div>
            )}
          </div>
          <p className="wb-addon-hint">点击插入，或拖到正文楼层。回复改变后，结果保留在待选区。</p>
          <div className="wb-image-auto">
            <div>
              <Check
                label="自动生图"
                checked={state.auto.enabled}
                onChange={(enabled) => run("auto", { enabled })}
              />
              <span className="wb-grow" />
              <label>
                每
                <input
                  aria-label="自动生图间隔"
                  type="number"
                  min="1"
                  max="100"
                  value={state.auto.every}
                  onChange={(e) => run("auto", { every: Number(e.target.value) })}
                />
                轮
              </label>
            </div>
            <div>
              <span>交付方式</span>
              <span className="wb-grow" />
              <small>{state.count} 轮已计入</small>
              <select
                aria-label="自动图片交付方式"
                value={state.auto.delivery}
                onChange={(e) => run("auto", { delivery: e.target.value })}
              >
                <option value="insert">插入触发楼层</option>
                <option value="pending">存入待选区</option>
              </select>
            </div>
          </div>
        </>
      )}
      {(error || task.error) && (
        <p className="wb-addon-error" role="alert">
          {error || task.error}
        </p>
      )}
      <p className="wb-addon-task" role="status">
        {task.label}
      </p>
    </section>
  );
}
