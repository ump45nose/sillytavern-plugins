import { randomId } from "../../host/ids";
import type { AddonRuntime, MessageTarget, StoryReply, TaskHost, TaskState } from "../types";
import { configuration, generateImage } from "./backends";
import { normalizeReferences, readImage, type ImageReference } from "./reference-files";
import { cleanPrompts, sceneSource } from "./prompts";
export interface ImageResult {
  id: string;
  url: string;
  positive: string;
  negative: string;
  target: MessageTarget;
  attached: boolean;
  created: number;
  name?: string;
  origin?: "upload";
}
export function createRuntime(host: TaskHost): AddonRuntime {
  const metadata = host.metadata(),
    key = host.snapshot().chatKey,
    listeners = new Set<() => void>();
  let version = 0,
    disposed = false,
    controller: AbortController | undefined,
    task: TaskState = { status: "idle", label: "" },
    target: MessageTarget | undefined;
  let data = {
    references: [] as ImageReference[],
    referencesReading: 0,
    positive: "",
    negative: "",
    source: "",
    results: (Array.isArray(metadata.results) ? metadata.results.slice(0, 40) : []) as ImageResult[],
    auto: { enabled: false, every: 3, delivery: "insert", ...(metadata.auto || {}) },
    count: 0,
  };
  for (const result of data.results) {
    try {
      const current = host.target(result.target.id);
      if (current.chatKey === result.target.chatKey && current.version === result.target.version)
        result.target = current;
    } catch {}
  }
  const seen = new Set<string>();
  const emit = () => {
    version++;
    listeners.forEach((fn) => fn());
  };
  const persist = async () => {
    if (disposed || host.snapshot().chatKey !== key) return;
    await host.saveMetadata({ version: 1, auto: data.auto, results: data.results.slice(0, 40) }, key);
  };
  const source = (selected: MessageTarget) =>
    sceneSource(host.exportSnapshot().messages, selected.id, configuration(host.config()).before);
  async function importImages(files: File[], selected: MessageTarget) {
    if (!files.length) return;
    if (task.status === "running") throw new Error("已有生图任务，请等待或取消。");
    if (!host.validTarget(selected)) throw new Error("目标楼层已改变，请重新选择插入位置。");
    controller = new AbortController();
    const signal = controller.signal;
    task = { status: "running", label: "正在读取图片" };
    emit();
    try {
      const images = await Promise.all(files.map((file) => readImage(file)));
      let attached = 0;
      for (const image of images) {
        if (signal.aborted || disposed || host.snapshot().chatKey !== key) return;
        task = { status: "running", label: "正在保存并插入图片" };
        emit();
        const url = await host.saveImage(image.dataUrl, signal);
        if (signal.aborted || disposed || host.snapshot().chatKey !== key) return;
        const result: ImageResult = {
          id: randomId(),
          url,
          positive: "",
          negative: "",
          target: selected,
          attached: false,
          created: Date.now(),
          name: image.name,
          origin: "upload",
        };
        data.results = [result, ...data.results].slice(0, 40);
        await persist();
        if (!signal.aborted && !disposed && host.validTarget(selected)) {
          result.attached = await host.attach(selected, url);
          if (result.attached) attached++;
          await persist();
        }
        emit();
      }
      if (signal.aborted || disposed) return;
      task = {
        status: "idle",
        label: attached === images.length ? `已插入 ${attached} 张图片` : "楼层已改变，图片已存入待选区",
      };
      emit();
    } catch (error) {
      if (!disposed && !signal.aborted) {
        task = {
          status: "error",
          label: "插入图片失败",
          error: error instanceof Error ? error.message : String(error),
        };
        emit();
        throw error;
      }
    }
  }
  async function execute(kind: string, options: any = {}) {
    if (data.referencesReading && kind !== "rewrite") throw new Error("参考图正在读取，请稍候。");
    if (task.status === "running") throw new Error("已有生图任务，请等待或取消。");
    target = options.target || target || host.target(host.exportSnapshot().messages.at(-1)?.id ?? 0);
    const captured = target!,
      config = configuration(host.config()),
      references = normalizeReferences(options.references ?? data.references);
    controller = new AbortController();
    const signal = controller.signal;
    task = { status: "running", label: kind === "generate" ? "正在生图" : "正在转写提示词" };
    emit();
    try {
      if (kind !== "generate") {
        data.source = source(captured);
        const prompt = config.template
          .replaceAll("{{scene}}", data.source)
          .replaceAll("{{style}}", config.style === "tags" ? "输出英文逗号分隔标签。" : "输出自然语言描述。");
        const result = cleanPrompts(await host.rewrite(prompt, config.profile, signal), config.style);
        if (signal.aborted || disposed) return;
        data = { ...data, ...result };
        emit();
      } else if (options.prompt) data = { ...data, ...cleanPrompts(options.prompt, config.style) };
      if (kind === "rewrite") {
        task = { status: "idle", label: "转写完成 · 可编辑最终提示词" };
        emit();
        return;
      }
      const final = cleanPrompts(
        JSON.stringify({ positive: data.positive, negative: data.negative }),
        config.style,
      );
      data = { ...data, ...final };
      task = { status: "running", label: "正在生成并保存图片" };
      emit();
      const image = await generateImage(config, final.positive, final.negative, host, signal, references);
      if (signal.aborted || disposed) return;
      const url = await host.saveImage(image, signal);
      if (signal.aborted || disposed || host.snapshot().chatKey !== key) return;
      const result: ImageResult = {
        id: randomId(),
        url,
        positive: final.positive,
        negative: final.negative,
        target: captured,
        attached: false,
        created: Date.now(),
      };
      data.results = [result, ...data.results].slice(0, 40);
      await persist(); // Keep the result in pending before attempting attachment.
      if (options.insert !== false && host.validTarget(captured)) {
        result.attached = await host.attach(captured, url, options.replace);
        await persist();
      }
      task = { status: "idle", label: result.attached ? "图片已插入目标楼层" : "图片已存入待选区" };
      emit();
    } catch (error) {
      if (!disposed && !signal.aborted) {
        task = {
          status: "error",
          label: "生图失败 · 可保留提示词重试",
          error: error instanceof Error ? error.message : String(error),
        };
        emit();
        throw error;
      }
    }
  }
  const stop = () => {
    controller?.abort();
    task = { status: "idle", label: "已取消 · 提示词保留" };
    emit();
  };
  async function action(name: string, ...args: any[]) {
    if (disposed) return;
    if (name === "stop") {
      stop();
      return;
    }
    if (name === "target") {
      target = args[0];
      data.source = source(target!);
      emit();
      return;
    }
    if (name === "references-reading") {
      data.referencesReading = Math.max(0, data.referencesReading + (args[0] ? 1 : -1));
      emit();
      return;
    }
    if (name === "references") {
      data.references = normalizeReferences(args[0]);
      emit();
      return;
    }
    if (name === "patch") {
      data = { ...data, ...args[0] };
      emit();
      return;
    }
    if (name === "config") {
      await host.saveConfig(configuration(args[0]));
      emit();
      return;
    }
    if (name === "open") {
      host.open(args[0] || "workspace");
      return;
    }
    if (name === "manual") {
      target = args[0];
      host.inputMode(target!);
      emit();
      return;
    }
    if (name === "auto") {
      data.auto = {
        ...data.auto,
        ...args[0],
        every: Math.max(1, Math.min(100, Math.floor(Number(args[0].every ?? data.auto.every) || 3))),
      };
      await persist();
      emit();
      return;
    }
    if (name === "reply") {
      const reply = args[0] as StoryReply;
      if (!data.auto.enabled || reply.target.chatKey !== key || !["normal", "continue"].includes(reply.type))
        return;
      const identity = reply.target.token + ":" + reply.target.version;
      if (seen.has(identity)) return;
      seen.add(identity);
      data.count++;
      emit();
      if (data.count < data.auto.every) return;
      if (task.status === "running") return;
      data.count = 0;
      await execute("rewrite-generate", { target: reply.target, insert: data.auto.delivery === "insert" });
      return;
    }
    if (name === "insert") {
      const result = data.results.find((r) => r.id === args[0]);
      if (!result) throw new Error("图片已不在当前聊天的结果区。");
      const selected = args[1] || result.target;
      if (!host.validTarget(selected) || !(await host.attach(selected, result.url)))
        throw new Error("目标楼层已改变，请重新选择插入位置。");
      result.attached = true;
      result.target = selected;
      await persist();
      if (task.status !== "running") task = { status: "idle", label: "图片已插入目标楼层" };
      emit();
      return;
    }
    if (name === "import") return importImages(args[0], args[1]);
    if (name === "remove") {
      const result = data.results.find((r) => r.id === args[0]);
      if (!result) return;
      if (result.attached) {
        if (!host.validTarget(result.target)) throw new Error("目标回复已改变，请先确认图片所在楼层。");
        await host.removeImage(result.target, result.url);
      }
      data.results = data.results.filter((r) => r !== result);
      await persist();
      emit();
      return;
    }
    if (name === "regenerate") {
      const result = data.results.find((r) => r.id === args[0]);
      if (result) {
        if (result.origin === "upload") throw new Error("本地图片没有生图提示词，请先填写提示词再生成。");
        data.positive = result.positive;
        data.negative = result.negative;
        await execute("generate", {
          target: result.target,
          replace: result.attached ? result.url : undefined,
        });
      }
      return;
    }
    if (["rewrite", "rewrite-generate", "generate"].includes(name)) return execute(name, args[0]);
  }
  return {
    subscribe: (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    revision: () => version,
    state: () => ({ ...data, target, config: configuration(host.config()) }),
    task: () => task,
    action,
    stop,
    dispose: () => {
      disposed = true;
      controller?.abort();
      listeners.clear();
    },
  };
}
