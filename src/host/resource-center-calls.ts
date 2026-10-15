export interface RpCall {
  eventId: string;
  profileId?: string;
  channelId?: string;
  baseUrl?: string;
  protocol?: string;
  model: string;
  occurredAt: string;
  origin: "live";
  result: "pending" | "success" | "failure" | "cancelled" | "unknown";
  latency?: number;
  ttft?: number;
  isStream: boolean;
  inputTokens?: number;
  outputTokens?: number;
  tokenBasis?: "provider";
  errorType?: string;
  statusCode?: number;
  streamStatus?: string;
}
const makeId = () =>
  [...crypto.getRandomValues(new Uint8Array(16))]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
const classify = (status: number, data?: any) => {
  const detail = `${data?.error?.type || ""} ${data?.error?.code || ""} ${data?.error?.message || ""} ${typeof data?.message === "string" ? data.message : ""}`;
  if (status === 429 || /rate.?limit|限流/i.test(detail)) return "rate";
  if (
    status === 402 ||
    data?.quota_error ||
    /quota|balance|insufficient|余额|额度/i.test(detail)
  )
    return "quota";
  if (
    status === 401 ||
    /authentication|invalid.*key|invalid.*token/i.test(detail)
  )
    return "key";
  if (status === 403) return "account";
  if (status === 400) return "input";
  return "upstream";
};

/** Per-call metadata only. Pending acknowledgements stay local until a terminal result. */
export class RpCallOutbox {
  delivering = false;
  error = "";
  lastAck = "";
  constructor(
    private settings: () => { url: string; token: string; device: string },
    private request: (path: string, body: any) => Promise<any>,
    private storage: Storage,
    private refresh: () => void,
  ) {}
  private prefix() {
    return `arc-rp-calls:${this.settings().device}:`;
  }
  entries(): any[] {
    const rows = [];
    for (let i = 0; i < this.storage.length; i++) {
      const key = this.storage.key(i)!;
      const value =
        key && key.startsWith(this.prefix()) ? this.storage.getItem(key) : null;
      if (value) rows.push(JSON.parse(value));
    }
    return rows.sort((a, b) =>
      a.event.occurredAt.localeCompare(b.event.occurredAt),
    );
  }
  put(event: RpCall) {
    try {
      const row = {
        device: this.settings().device,
        event,
        revision: event.result === "pending" ? 1 : 2,
        acknowledged: false,
      };
      this.storage.setItem(this.prefix() + event.eventId, JSON.stringify(row));
      this.refresh();
      void this.deliver();
    } catch (e) {
      this.error = `调用记录未能保存：${String(e)}`;
      this.refresh();
    }
  }
  async deliver() {
    if (this.delivering || !this.settings().url || !this.settings().token)
      return;
    this.delivering = true;
    try {
      for (const row of this.entries().filter((r) => !r.acknowledged)) {
        const result = await this.request("calls", {
          device: row.device,
          events: [row.event],
        });
        if (!result.acknowledgedIds?.includes(row.event.eventId))
          throw new Error("中心未确认调用记录");
        const key = this.prefix() + row.event.eventId,
          current = this.storage.getItem(key);
        if (current && JSON.parse(current).revision === row.revision) {
          if (row.event.result === "pending")
            this.storage.setItem(
              key,
              JSON.stringify({ ...row, acknowledged: true }),
            );
          else this.storage.removeItem(key);
        }
        this.error = "";
        this.lastAck = new Date().toISOString();
      }
    } catch (e) {
      this.error = String(e);
    } finally {
      this.delivering = false;
      this.refresh();
      // A final result may have replaced an in-flight pending receipt.
      if (!this.error && this.entries().some((r) => !r.acknowledged))
        void this.deliver();
    }
  }
}

/** Observe the existing consumer's stream; retain only usage and outcome, never message text. */
class ResponseFacts {
  inputTokens?: number;
  outputTokens?: number;
  ttft?: number;
  terminal = false;
  sawSseData = false;
  private decoder = new TextDecoder();
  private buffer = "";
  private data = "";
  private oversized = false;
  private lineOversized = false;
  constructor(
    private started: number,
    private now: () => number,
    private finish: (result: RpCall["result"], errorType?: string) => void,
  ) {}
  inspect(d: any) {
    if (!d || typeof d !== "object") return;
    const usage = d.usage || d.message?.usage || d.response?.usage;
    const gemini = d.usageMetadata;
    const input =
      usage?.prompt_tokens ?? usage?.input_tokens ?? gemini?.promptTokenCount;
    const output =
      usage?.completion_tokens ??
      usage?.output_tokens ??
      gemini?.candidatesTokenCount;
    if (Number.isFinite(input) && input >= 0) this.inputTokens = input;
    if (Number.isFinite(output) && output >= 0) this.outputTokens = output;
    const delta = d.choices?.[0]?.delta;
    const first =
      delta?.content ||
      delta?.reasoning_content ||
      delta?.reasoning ||
      delta?.tool_calls?.length ||
      d.delta?.text ||
      d.delta?.thinking ||
      d.delta?.partial_json ||
      (d.type === "response.output_text.delta" && d.delta) ||
      d.candidates?.[0]?.content?.parts?.some(
        (p: any) => p.text || p.functionCall,
      );
    if (first && this.ttft === undefined) this.ttft = this.now() - this.started;
    if (
      d.error ||
      d.quota_error ||
      d.type === "error" ||
      d.type === "response.failed"
    ) {
      this.finish("failure", classify(0, d));
      return;
    }
    if (d.type === "message_stop") {
      this.terminal = true;
      this.finish("success");
    }
    if (
      d.type === "response.completed" ||
      d.choices?.some((c: any) => c.finish_reason) ||
      d.candidates?.some((c: any) => c.finishReason)
    )
      this.terminal = true;
  }
  private line(line: string) {
    if (!line) {
      if (!this.oversized && this.data) {
        const raw = this.data.slice(0, -1);
        if (raw === "[DONE]") {
          this.terminal = true;
          this.finish("success");
        } else {
          try {
            this.inspect(JSON.parse(raw));
          } catch {
            /* Native parser owns protocol errors. */
          }
        }
      }
      this.data = "";
      this.oversized = false;
    } else if (!this.oversized && line.startsWith("data:")) {
      this.sawSseData = true;
      this.data += line.slice(5).replace(/^ /, "") + "\n";
      if (this.data.length > 512 * 1024) {
        this.data = "";
        this.oversized = true;
      }
    }
  }
  chunk(bytes: Uint8Array) {
    this.buffer += this.decoder.decode(bytes, { stream: true });
    let end;
    while ((end = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, end).replace(/\r$/, "");
      this.buffer = this.buffer.slice(end + 1);
      if (this.lineOversized) {
        this.lineOversized = false;
        this.oversized = true;
      } else this.line(line);
    }
    if (this.buffer.length > 512 * 1024) {
      this.buffer = "";
      this.lineOversized = true;
    }
  }
  end() {
    this.buffer += this.decoder.decode();
    if (this.buffer && !this.lineOversized)
      this.line(this.buffer.replace(/\r$/, ""));
    this.line("");
    this.finish(this.terminal ? "success" : "unknown");
  }
}

export function observeRpCalls(
  host: Pick<Window, "fetch" | "location">,
  snapshot: (body: any) => Partial<RpCall> | null,
  report: (event: RpCall) => void,
  onError: (error: unknown) => void,
  now = () => performance.now(),
) {
  const original = host.fetch;
  const paths = new Set([
    "/api/backends/chat-completions/generate",
    "/api/backends/text-completions/generate",
  ]);
  host.fetch = function (
    this: typeof host,
    input: RequestInfo | URL,
    init?: RequestInit,
  ) {
    let event: RpCall | undefined;
    try {
      const url = new URL(
        typeof input === "string" || input instanceof URL
          ? String(input)
          : input.url,
        host.location.href,
      );
      if (
        url.origin === host.location.origin &&
        paths.has(url.pathname) &&
        (init?.method || "GET").toUpperCase() === "POST" &&
        typeof init?.body === "string"
      ) {
        const body = JSON.parse(init.body),
          meta = snapshot(body);
        if (meta)
          event = {
            ...meta,
            eventId: makeId(),
            model: String(body.model || ""),
            isStream: !!body.stream,
            origin: "live",
            occurredAt: new Date().toISOString(),
            result: "pending",
          };
      }
    } catch (e) {
      onError(e);
    }
    if (!event) return Reflect.apply(original, this, [input, init]);
    const call = event,
      started = now();
    let finished = false;
    const safeReport = (e: RpCall) => {
      try {
        report(e);
      } catch (error) {
        onError(error);
      }
    };
    const facts = new ResponseFacts(started, now, finish);
    const abort = () => finish("cancelled", "cancelled");
    init?.signal?.addEventListener("abort", abort, { once: true });
    function finish(result: RpCall["result"], errorType?: string) {
      if (finished) return;
      finished = true;
      init?.signal?.removeEventListener("abort", abort);
      safeReport({
        ...call,
        result,
        latency: now() - started,
        ...(facts.ttft !== undefined ? { ttft: facts.ttft } : {}),
        ...(facts.inputTokens !== undefined
          ? { inputTokens: facts.inputTokens }
          : {}),
        ...(facts.outputTokens !== undefined
          ? { outputTokens: facts.outputTokens }
          : {}),
        ...(facts.inputTokens !== undefined || facts.outputTokens !== undefined
          ? { tokenBasis: "provider" as const }
          : {}),
        ...(errorType ? { errorType } : {}),
        ...(call.isStream
          ? {
              streamStatus:
                result === "success"
                  ? "completed"
                  : result === "cancelled"
                    ? "cancelled"
                    : result === "failure"
                      ? "disconnected"
                      : "unknown",
            }
          : {}),
      });
    }
    safeReport({ ...call });
    let request: Promise<Response>;
    try {
      request = Reflect.apply(original, this, [input, init]);
    } catch (e) {
      finish("failure", "upstream");
      throw e;
    }
    return request.then(
      (response) => {
        call.statusCode = response.status;
        if (!response.ok || !call.isStream) {
          const json = response.json.bind(response),
            text = response.text.bind(response);
          const inspect = (data: any) => {
            if (!response.ok)
              finish("failure", classify(response.status, data));
            else {
              facts.inspect(data);
              finish(
                data?.choices?.length ||
                  data?.content?.length ||
                  data?.candidates?.length ||
                  data?.output?.length
                  ? "success"
                  : "unknown",
              );
            }
          };
          const rejected = (e: any) => {
            finish(
              e?.name === "AbortError" ? "cancelled" : "failure",
              e?.name === "AbortError" ? "cancelled" : "upstream",
            );
            throw e;
          };
          response.json = async () => {
            try {
              const data = await json();
              inspect(data);
              return data;
            } catch (e) {
              return rejected(e);
            }
          };
          response.text = async () => {
            try {
              const raw = await text();
              let data;
              if (raw.length <= 512 * 1024) {
                try {
                  data = JSON.parse(raw);
                } catch {
                  /* Keep the original text for native error handling. */
                }
              }
              inspect(data);
              return raw;
            } catch (e) {
              return rejected(e);
            }
          };
          return response;
        }
        if (!response.body) {
          finish("unknown");
          return response;
        }
        const reader = response.body.getReader();
        let errorJson = "";
        const stream = new ReadableStream({
          async pull(controller) {
            try {
              const { value, done } = await reader.read();
              if (done) {
                if (!facts.sawSseData) {
                  try {
                    facts.inspect(JSON.parse(errorJson));
                  } catch {
                    /* Native error handling owns unsupported bodies. */
                  }
                }
                facts.end();
                controller.close();
              } else {
                facts.chunk(value);
                if (!facts.sawSseData && errorJson.length < 512 * 1024)
                  errorJson += new TextDecoder().decode(
                    value.subarray(0, 512 * 1024 - errorJson.length),
                  );
                controller.enqueue(value);
              }
            } catch (e) {
              finish(
                (e as Error).name === "AbortError" ? "cancelled" : "failure",
                (e as Error).name === "AbortError" ? "cancelled" : "upstream",
              );
              controller.error(e);
            }
          },
          cancel(reason) {
            finish("cancelled", "cancelled");
            return reader.cancel(reason);
          },
        });
        return new Response(stream, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      },
      (error) => {
        finish(
          error?.name === "AbortError" ? "cancelled" : "failure",
          error?.name === "AbortError" ? "cancelled" : "upstream",
        );
        throw error;
      },
    );
  } as typeof fetch;
  return () => {
    host.fetch = original;
  };
}
