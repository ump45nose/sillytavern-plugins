import { randomId } from "../../host/ids";
import { unzipSync } from "fflate";
import type { TaskHost } from "../types";
import {
  buildGptImagePayload,
  buildNanobananaPayload,
  getOpenAICompatibleApiUrl,
  getNanobananaApiUrl,
  getNanobananaAuthHeaders,
  extractProviderImageSource,
  materializeProviderImageSource,
  imageResponseToDataUrl,
} from "./vendor/qig/provider-adapters.js";
import {
  buildComfyBuiltinWorkflow,
  parseComfyWorkflow,
  buildComfyPromptRequest,
  parseComfyPromptResponse,
  pollComfyHistory,
  buildComfyViewUrl,
  cancelComfyPrompt,
} from "./vendor/qig/comfyui-backend.js";
import { normalizeA1111BaseUrl } from "./vendor/qig/a1111-runtime.js";
import { defaultTemplate } from "./prompts";
import { normalizeReferences, referenceData, type ImageReference } from "./reference-files";
export const providers = ["openai", "gemini", "novelai", "a1111", "comfyui"] as const;
export type Provider = (typeof providers)[number];
export interface ImageConfig {
  provider: Provider;
  url: string;
  key: string;
  model: string;
  width: number;
  height: number;
  steps: number;
  scale: number;
  seed: number;
  sampler: string;
  scheduler: string;
  workflow: string;
  template: string;
  profile: string;
  style: "tags" | "natural";
  before: number;
  timeout: number;
  referenceStrength: number;
}
export const defaultModels: Record<Provider, string> = {
  openai: "gpt-image-1",
  gemini: "gemini-2.5-flash-image",
  novelai: "nai-diffusion-4-curated-preview",
  a1111: "",
  comfyui: "model.safetensors",
};
export function configuration(value: any): ImageConfig {
  const provider: Provider = providers.includes(value.provider) ? value.provider : "openai";
  return {
    provider,
    referenceStrength: Math.max(0.01, Math.min(1, Number(value.referenceStrength) || 0.65)),
    url: String(value.url || ""),
    key: String(value.key || ""),
    model: String(value.model ?? defaultModels[provider]),
    width: Math.max(256, Math.min(2048, Math.round((Number(value.width) || 1024) / 64) * 64)),
    height: Math.max(256, Math.min(2048, Math.round((Number(value.height) || 1024) / 64) * 64)),
    steps: Math.max(1, Math.min(100, Number(value.steps) || 28)),
    scale: Math.max(1, Math.min(30, Number(value.scale) || 7)),
    seed: Number.isFinite(Number(value.seed)) ? Number(value.seed) : -1,
    sampler: String(value.sampler || "euler"),
    scheduler: String(value.scheduler || "normal"),
    workflow: String(value.workflow || ""),
    template: String(value.template || defaultTemplate),
    profile: String(value.profile || ""),
    style: value.style === "tags" ? "tags" : "natural",
    before: Math.max(0, Math.min(30, Number(value.before) || 0)),
    timeout: Math.max(30, Math.min(600, Number(value.timeout) || 300)),
  };
}
function baseURL(value: string) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error("后端地址需要有效的 HTTP 地址；密钥请填入独立字段。");
  return url.href.replace(/\/$/, "");
}
export async function generateImage(
  config: ImageConfig,
  positive: string,
  negative: string,
  host: Pick<TaskHost, "request">,
  parent: AbortSignal,
  inputReferences: readonly ImageReference[] = [],
): Promise<string> {
  const references = normalizeReferences(inputReferences),
    images = references.map((r) => referenceData(r.dataUrl));
  if (["a1111", "novelai", "comfyui"].includes(config.provider) && references.length > 1)
    throw new Error("当前后端使用一张参考图作为底图，请移除多余参考图。");
  if (
    images.length &&
    ((config.provider === "openai" && !config.url && !config.key) ||
      (config.provider === "novelai" && !config.key))
  )
    throw new Error("酒馆内置生图通道不支持参考图，请在生图配置中填写独立后端地址和密钥。");
  const signal = AbortSignal.any([parent, AbortSignal.timeout(config.timeout * 1000)]),
    seed = config.seed >= 0 ? config.seed : Math.floor(Math.random() * 2147483647);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(config.key ? { Authorization: `Bearer ${config.key}` } : {}),
  };
  const post = async (url: string, body: unknown, custom = headers) => {
    const response = await fetch(url, {
      method: "POST",
      headers: custom,
      body: JSON.stringify(body),
      signal,
      redirect: "error",
    });
    if (!response.ok) throw new Error(`生图后端返回 HTTP ${response.status}，请检查配置。`);
    return response;
  };
  let requestUrl = "",
    response: Response;
  if (config.provider === "comfyui") {
    const base = baseURL(config.url);
    if (
      images.length &&
      config.workflow.trim() &&
      !/%reference_image%|\{\{\s*reference_image\s*\}\}/.test(config.workflow)
    )
      throw new Error("自定义 ComfyUI 工作流需要在 LoadImage 节点中使用 %reference_image% 占位符。");
    let referenceImage = "";
    if (images.length) {
      const upload = new FormData();
      upload.set("image", images[0].blob, "wb-ref-" + randomId() + "." + images[0].mime.split("/")[1]);
      upload.set("type", "input");
      const uploaded = await fetch(base + "/upload/image", {
        method: "POST",
        body: upload,
        headers: config.key ? { Authorization: `Bearer ${config.key}` } : {},
        signal,
        redirect: "error",
      });
      if (!uploaded.ok) throw new Error("ComfyUI 参考图上传失败。");
      const file = await uploaded.json();
      if (typeof file.name !== "string" || !file.name) throw new Error("ComfyUI 未返回参考图名称。");
      referenceImage = (file.subfolder ? file.subfolder + "/" : "") + file.name;
    }
    const workflow = config.workflow.trim()
      ? parseComfyWorkflow(config.workflow.replace(/\{\{\s*reference_image\s*\}\}/g, "%reference_image%"))
      : buildComfyBuiltinWorkflow({
          modelName: config.model,
          seed,
          steps: config.steps,
          cfgScale: config.scale,
          samplerName: config.sampler,
          schedulerName: config.scheduler,
          denoise: 1,
          prompt: positive,
          negativePrompt: negative,
          width: config.width,
          height: config.height,
        });
    const graph = (workflow as any).workflow || workflow;
    if (referenceImage && !config.workflow.trim()) {
      graph["10"] = { class_type: "LoadImage", inputs: { image: referenceImage } };
      graph["5"] = { class_type: "VAEEncode", inputs: { pixels: ["10", 0], vae: ["4", 2] } };
      graph["3"].inputs.denoise = config.referenceStrength;
    }
    const body = buildComfyPromptRequest(graph, {
      prompt: positive,
      negative,
      seed,
      steps: config.steps,
      width: config.width,
      height: config.height,
      cfg: config.scale,
      reference_image: referenceImage,
    });
    const started = parseComfyPromptResponse(
      await (await post(base + "/prompt", { ...body, client_id: randomId() })).json(),
    );
    const cancel = () => {
      void cancelComfyPrompt(started.prompt_id, {
        baseUrl: base,
        tryJobsCancel: true,
        allowLegacyInterrupt: false,
      }).catch(() => {});
    };
    signal.addEventListener("abort", cancel, { once: true });
    try {
      const result = await pollComfyHistory(started.prompt_id, {
        baseUrl: base,
        signal,
        timeoutMs: config.timeout * 1000,
      });
      requestUrl = buildComfyViewUrl(base, result.images[0]);
      response = await fetch(requestUrl, { signal, redirect: "error" });
      if (!response.ok) throw new Error("ComfyUI 图片读取失败。");
      return await imageResponseToDataUrl(response);
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  }
  if (config.provider === "novelai") {
    const body = {
      prompt: positive,
      negative_prompt: negative,
      model: config.model,
      width: config.width,
      height: config.height,
      steps: config.steps,
      scale: config.scale,
      seed,
      sampler: config.sampler === "euler" ? "k_euler" : config.sampler,
      scheduler: config.scheduler === "normal" ? "native" : config.scheduler,
    };
    if (!config.key) {
      response = await host.request("/api/novelai/generate-image", body, signal);
      if (!response.ok) throw new Error("NovelAI 生图失败，请配置酒馆的 NovelAI 密钥。");
      const text = await response.text();
      return `data:image/png;base64,${text.replace(/^"|"$/g, "")}`;
    }
    requestUrl = baseURL(config.url || "https://image.novelai.net") + "/ai/generate-image";
    const { prompt, negative_prompt, model, ...parameters } = body;
    response = await post(requestUrl, {
      action: images.length ? "img2img" : "generate",
      input: prompt,
      model,
      parameters: {
        ...parameters,
        ...(images.length ? { image: images[0].base64, strength: config.referenceStrength, noise: 0.2 } : {}),
        params_version: 3,
        n_samples: 1,
        negative_prompt,
        v4_prompt: {
          caption: { base_caption: prompt, char_captions: [] },
          use_coords: false,
          use_order: true,
        },
        v4_negative_prompt: { caption: { base_caption: negative_prompt, char_captions: [] } },
      },
    });
    const files = unzipSync(new Uint8Array(await response.arrayBuffer())),
      png = Object.entries(files).find(([name]) => name.endsWith(".png"));
    if (!png) throw new Error("NovelAI 未返回 PNG 图片。");
    let binary = "";
    for (const byte of png[1]) binary += String.fromCharCode(byte);
    return "data:image/png;base64," + btoa(binary);
  }
  if (config.provider === "a1111") {
    requestUrl =
      normalizeA1111BaseUrl(baseURL(config.url)) +
      (images.length ? "/sdapi/v1/img2img" : "/sdapi/v1/txt2img");
    response = await post(requestUrl, {
      prompt: positive,
      negative_prompt: negative,
      width: config.width,
      height: config.height,
      steps: config.steps,
      cfg_scale: config.scale,
      seed,
      sampler_name: config.sampler,
      batch_size: 1,
      n_iter: 1,
      ...(images.length
        ? { init_images: references.map((r) => r.dataUrl), denoising_strength: config.referenceStrength }
        : {}),
      ...(config.model
        ? {
            override_settings: { sd_model_checkpoint: config.model },
            override_settings_restore_afterwards: true,
          }
        : {}),
    });
  } else if (config.provider === "gemini") {
    if (!config.key) throw new Error("请填写 Gemini API 密钥。");
    requestUrl = getNanobananaApiUrl(config.url ? baseURL(config.url) : "", config.model, "");
    response = await post(
      requestUrl,
      buildNanobananaPayload({
        endpointUrl: requestUrl,
        model: config.model,
        parts: [
          { text: positive + (negative ? "\nAvoid: " + negative : "") },
          ...images.map((image) => ({ inlineData: { mimeType: image.mime, data: image.base64 } })),
        ],
        generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
        safetySettings: undefined,
      }),
      {
        "Content-Type": "application/json",
        ...getNanobananaAuthHeaders(requestUrl, config.key),
      } as unknown as Record<string, string>,
    );
  } else {
    const payload = buildGptImagePayload({
      model: config.model,
      prompt: positive,
      negative,
      size: `${config.width}x${config.height}`,
    });
    if (images.length) {
      if (/^dall-e/.test(config.model)) throw new Error("参考图需要支持图片编辑的模型，如 GPT Image。");
      requestUrl = getOpenAICompatibleApiUrl(baseURL(config.url || "https://api.openai.com/v1")).replace(
        /\/images\/generations$/,
        "/images/edits",
      );
      const body = new FormData();
      for (const [name, value] of Object.entries(payload)) body.append(name, String(value));
      images.forEach((image, i) =>
        body.append("image[]", image.blob, `reference-${i + 1}.${image.mime.split("/")[1]}`),
      );
      response = await fetch(requestUrl, {
        method: "POST",
        body,
        headers: config.key ? { Authorization: `Bearer ${config.key}` } : {},
        signal,
        redirect: "error",
      });
      if (!response.ok) throw new Error(`参考图生图返回 HTTP ${response.status}，请确认后端支持图片编辑。`);
    } else if (!config.url && !config.key) {
      response = await host.request(
        "/api/openai/generate-image",
        { ...payload, response_format: "b64_json" },
        signal,
      );
      requestUrl = location.origin + "/api/openai/generate-image";
      if (!response.ok) throw new Error("OpenAI 生图失败，请配置酒馆的 OpenAI 密钥。");
    } else {
      requestUrl = getOpenAICompatibleApiUrl(baseURL(config.url || "https://api.openai.com/v1"));
      response = await post(requestUrl, {
        ...payload,
        ...(/^dall-e/.test(config.model) ? { response_format: "b64_json" } : {}),
      });
    }
  }
  const source = extractProviderImageSource(await response.json());
  if (!source) throw new Error("后端未返回可用图片。");
  const materialized = await (
    materializeProviderImageSource as (source: string, options: any) => Promise<string>
  )(source, {
    requestUrl,
    responseUrl: response.url,
    headers,
    signal,
    forceFetch: true,
    allowBrowserFallback: false,
  });
  if (!materialized.startsWith("data:image/")) throw new Error("图片未能读取为本地附件。");
  return materialized;
}
