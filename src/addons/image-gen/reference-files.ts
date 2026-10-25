import { randomId } from "../../host/ids";
export interface ImageReference {
  id: string;
  name: string;
  dataUrl: string;
}
export const referenceLimit = 4,
  referenceBytes = 8 * 1024 * 1024;
export function referenceData(value: string) {
  const match = value.match(/^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$/);
  if (!match || match[2].length > Math.ceil((referenceBytes * 4) / 3) + 4)
    throw new Error("参考图需要 PNG、JPEG 或 WebP，每张不超过 8 MB。");
  const bytes = Uint8Array.from(atob(match[2]), (c) => c.charCodeAt(0));
  const valid =
    match[1] === "image/png"
      ? bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71
      : match[1] === "image/jpeg"
        ? bytes[0] === 255 && bytes[1] === 216
        : bytes.slice(0, 4).every((b, i) => b === "RIFF".charCodeAt(i)) &&
          bytes.slice(8, 12).every((b, i) => b === "WEBP".charCodeAt(i));
  if (bytes.length < 12 || !valid) throw new Error("参考图文件内容与格式不一致。");
  return { mime: match[1], base64: match[2], blob: new Blob([bytes], { type: match[1] }) };
}
export function normalizeReferences(values: unknown): ImageReference[] {
  if (!Array.isArray(values) || values.length > referenceLimit) throw new Error("最多插入 4 张参考图。");
  return values.map((v) => {
    referenceData(String(v.dataUrl || ""));
    return {
      id: String(v.id || randomId()),
      name: String(v.name || "参考图").slice(0, 100),
      dataUrl: String(v.dataUrl),
    };
  });
}
export async function readReference(file: File): Promise<ImageReference> {
  if (file.size > referenceBytes || !["image/png", "image/jpeg", "image/webp"].includes(file.type))
    throw new Error("参考图需要 PNG、JPEG 或 WebP，每张不超过 8 MB。");
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("参考图读取失败。"));
    reader.readAsDataURL(file);
  });
  const data = referenceData(dataUrl),
    bitmap = await createImageBitmap(data.blob);
  bitmap.close();
  return { id: randomId(), name: file.name || "参考图", dataUrl };
}
