/** Streaming metadata only. Parsed content is discarded immediately and never enters the journal. */
export class ResponseFacts {
  constructor(started = performance.now()) {
    this.started = started;
    this.buffer = "";
    this.decoder = new TextDecoder();
    this.terminal = false;
    this.error = false;
    this.oversized = false;
  }
  inspect(data) {
    if (!data || typeof data !== "object") return;
    if (data.error || data.type === "error") {
      this.error = true;
      const code = String(data.error?.code || data.error?.type || data.error?.status || "").toLowerCase();
      this.errorType = /quota|balance|credit|billing/.test(code)
        ? "quota"
        : /rate|429|exhausted/.test(code)
          ? "rate"
          : /key|auth|401|403/.test(code)
            ? "key"
            : /account|deactivat|suspend/.test(code)
              ? "account"
              : "upstream";
      return;
    }
    const choices = data.choices || [],
      delta = data.delta || {};
    if (
      choices.some((c) => c.finish_reason != null) ||
      ["response.completed", "message_stop"].includes(data.type) ||
      data.candidates?.some((c) => c.finishReason)
    )
      this.terminal = true;
    if (
      choices.some((c) => c.delta?.content || c.delta?.reasoning_content || c.text || c.message?.content) ||
      delta.text ||
      delta.thinking ||
      data.candidates?.some((c) => c.content?.parts?.some((p) => p.text)) ||
      data.type === "response.output_text.delta"
    )
      this.ttft ??= performance.now() - this.started;
    const u = data.usage || data.response?.usage || data.usageMetadata;
    if (u) {
      this.inputTokens = u.prompt_tokens ?? u.input_tokens ?? u.promptTokenCount ?? this.inputTokens;
      this.outputTokens =
        u.completion_tokens ?? u.output_tokens ?? u.candidatesTokenCount ?? this.outputTokens;
    }
    if (data.type === "message_start" && data.message?.usage) this.inspect({ usage: data.message.usage });
    if (data.choices?.length && !choices.some((c) => c.delta)) this.terminal = true;
    if (
      data.content?.length ||
      data.output?.length ||
      (data.candidates?.length && !data.candidates.every((c) => !c.finishReason))
    )
      this.terminal = true;
  }
  line(line) {
    if (!line.startsWith("data:")) return;
    const data = line.slice(5).trim();
    if (data === "[DONE]") {
      this.terminal = true;
      return;
    }
    try {
      this.inspect(JSON.parse(data));
    } catch {
      /* partial/unsupported SSE metadata */
    }
  }
  feed(chunk, stream) {
    const text = typeof chunk === "string" ? chunk : this.decoder.decode(chunk, { stream: true });
    if (!stream) {
      if (this.buffer.length + text.length <= 262144) this.buffer += text;
      else this.oversized = true;
      return;
    }
    for (const part of text.split(/(\n)/)) {
      if (part === "\n") {
        if (!this.oversized) this.line(this.buffer.replace(/\r$/, ""));
        this.buffer = "";
        this.oversized = false;
      } else if (!this.oversized) {
        if (this.buffer.length + part.length > 65536) {
          this.buffer = "";
          this.oversized = true;
        } else this.buffer += part;
      }
    }
  }
  end(stream) {
    if (stream) {
      if (!this.oversized) this.line(this.buffer);
    } else if (!this.oversized) {
      try {
        this.inspect(JSON.parse(this.buffer));
      } catch {}
    }
    this.buffer = "";
    return {
      ...(this.ttft != null ? { ttft: this.ttft } : {}),
      ...(Number.isInteger(this.inputTokens) ? { inputTokens: this.inputTokens } : {}),
      ...(Number.isInteger(this.outputTokens) ? { outputTokens: this.outputTokens } : {}),
      ...(this.inputTokens != null || this.outputTokens != null ? { tokenBasis: "provider" } : {}),
    };
  }
}
