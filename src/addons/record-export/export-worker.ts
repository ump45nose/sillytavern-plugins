import { exportParts, filterMessage, parseMessage, tagStatistics, type ExportMessage, type ExportOptions, type ParsedMessage } from "./xml-export";
let generation = 0, messages: ParsedMessage[] = [], results: ExportMessage[] = [], resultId = -1;
const pause = () => new Promise(resolve => setTimeout(resolve, 0));
self.onmessage = async (event: MessageEvent) => {
  const request = event.data;
  try {
    if (request.type === "scan") {
      const token = ++generation, parsed: ParsedMessage[] = []; messages = []; results = []; resultId = -1;
      for (let offset = 0; offset < request.messages.length; offset += 16) {
        if (token !== generation) return;
        parsed.push(...request.messages.slice(offset, offset + 16).map(parseMessage));
        self.postMessage({ type: "progress", id: request.id, done: parsed.length, total: request.messages.length }); await pause();
      }
      if (token !== generation) return;
      messages = parsed;
      self.postMessage({ type: "scanned", id: request.id, tags: tagStatistics(messages), total: messages.length });
    } else if (request.type === "filter") {
      const token = ++generation, options = request.options as ExportOptions, next: ExportMessage[] = [], warnings: { id: number; message: string }[] = [];
      resultId = -1;
      for (let offset = 0; offset < messages.length; offset += 32) {
        if (token !== generation) return;
        for (const message of messages.slice(offset, offset + 32)) {
          const result = filterMessage(message, options); if (result) next.push(result);
          if (message.id + 1 >= options.from && message.id + 1 <= options.to && options.roles.includes(message.role))
            for (const warning of message.warnings) warnings.push({ id: message.id, message: warning.message });
        }
        await pause();
      }
      if (token !== generation) return;
      results = next; resultId = request.id;
      self.postMessage({ type: "result", id: request.id, total: messages.length, matched: results.length, characters: results.reduce((sum, message) => sum + message.text.length, 0),
        preview: results.slice(0, 30).map(message => ({ ...message, text: message.text.slice(0, 12000) })), warnings: warnings.slice(0, 100), warningCount: warnings.length });
    } else if (request.type === "download") {
      if (request.resultId !== resultId || !results.length) throw new Error("结果已变化，请等待预览更新后再导出。");
      self.postMessage({ type: "download", id: request.id, blob: new Blob(exportParts(results, request.format, request.metadata), { type: request.format === "md" ? "text/markdown;charset=utf-8" : "text/plain;charset=utf-8" }) });
    }
  } catch (error) { self.postMessage({ type: "error", id: request.id, message: error instanceof Error ? error.message : String(error) }); }
};
