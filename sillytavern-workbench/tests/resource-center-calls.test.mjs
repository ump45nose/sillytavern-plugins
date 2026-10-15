import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
const result = await build({
  entryPoints: ["src/host/resource-center-calls.ts"],
  bundle: true,
  write: false,
  format: "esm",
  platform: "node",
});
const { observeRpCalls, RpCallOutbox } = await import(
  "data:text/javascript;base64," +
    Buffer.from(result.outputFiles[0].contents).toString("base64")
);
const request = {
  method: "POST",
  body: JSON.stringify({
    model: "native",
    stream: true,
    messages: [{ role: "user", content: "PRIVATE PROMPT" }],
    proxy_password: "PRIVATE KEY",
  }),
};
const meta = () => ({
  profileId: "p",
  baseUrl: "https://rp.invalid/v1",
  protocol: "OpenAI",
});
function fixture(responder) {
  const records = [];
  let count = 0,
    seen;
  const host = {
    location: new URL("http://tavern.invalid"),
    fetch: async (...args) => {
      count++;
      seen = args;
      return responder(...args);
    },
  };
  observeRpCalls(
    host,
    meta,
    (e) => records.push(e),
    (e) => {
      throw e;
    },
  );
  return { host, records, count: () => count, seen: () => seen };
}
const sse = (chunks) =>
  new Response(
    new ReadableStream({
      start(c) {
        for (const chunk of chunks) c.enqueue(new TextEncoder().encode(chunk));
        c.close();
      },
    }),
    { headers: { "content-type": "text/event-stream", "x-original": "kept" } },
  );

test("one native request, byte-identical stream, real usage and completion; no prompts or response text in telemetry", async () => {
  const raw =
    'data: {"choices":[{"delta":{"content":"PRIVATE RESPONSE"}}]}\n\ndata: {"usage":{"prompt_tokens":23,"completion_tokens":9}}\n\ndata: [DONE]\n\n';
  const f = fixture(() => {
    const r = sse([raw.slice(0, 18), raw.slice(18)]);
    r.headers.set("content-type", "text/plain");
    return r;
  });
  const response = await f.host.fetch(
    "/api/backends/chat-completions/generate",
    request,
  );
  assert.equal(await response.text(), raw);
  assert.equal(response.headers.get("x-original"), "kept");
  assert.equal(f.count(), 1);
  assert.equal(f.seen()[1], request);
  assert.equal(f.records.length, 2);
  const final = f.records[1];
  assert.equal(final.result, "success");
  assert.equal(final.inputTokens, 23);
  assert.equal(final.outputTokens, 9);
  assert.ok(final.ttft >= 0);
  assert.equal(final.eventId, f.records[0].eventId);
  assert.ok(!JSON.stringify(f.records).includes("PRIVATE"));
});

test("HTTP errors, JSON errors, in-stream failures, cancellation and missing terminators keep distinct outcomes", async () => {
  const http = fixture(
    () =>
      new Response('{"error":{"message":"quota exhausted"}}', { status: 403 }),
  );
  const r = await http.host.fetch(
    "/api/backends/chat-completions/generate",
    request,
  );
  assert.equal(await r.text(), '{"error":{"message":"quota exhausted"}}');
  assert.equal(http.records[1].errorType, "quota");
  const json = fixture(
    () =>
      new Response(
        JSON.stringify({
          error: { type: "rate_limit_error", message: "PRIVATE RESPONSE" },
        }),
        { headers: { "content-type": "application/json" } },
      ),
  );
  await (
    await json.host.fetch("/api/backends/chat-completions/generate", {
      ...request,
      body: JSON.stringify({ model: "native", stream: false }),
    })
  ).json();
  assert.equal(json.records[1].result, "failure");
  assert.equal(json.records[1].errorType, "rate");
  const error = fixture(() =>
    sse([
      'data: {"error":{"type":"rate_limit_error","message":"PRIVATE RESPONSE"}}\n\n',
    ]),
  );
  await (
    await error.host.fetch("/api/backends/chat-completions/generate", request)
  ).text();
  assert.equal(error.records[1].result, "failure");
  assert.equal(error.records[1].errorType, "rate");
  assert.ok(!JSON.stringify(error.records).includes("PRIVATE"));
  const stopped = fixture(() =>
    sse(['data: {"choices":[{"delta":{"content":"x"}}]}\n\n']),
  );
  const signal = new AbortController();
  const stream = await stopped.host.fetch(
    "/api/backends/chat-completions/generate",
    { ...request, signal: signal.signal },
  );
  signal.abort();
  await stream.text();
  assert.equal(stopped.records[1].result, "cancelled");
  const eof = fixture(() =>
    sse(['data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']),
  );
  await (
    await eof.host.fetch("/api/backends/chat-completions/generate", request)
  ).text();
  assert.equal(eof.records[1].result, "unknown");
});

test("Anthropic and Gemini usage and completion are observed; unconfigured capture and non-generation calls add no telemetry", async () => {
  const a = fixture(() =>
    sse([
      'data: {"type":"message_start","message":{"usage":{"input_tokens":17,"output_tokens":0}}}\n\ndata: {"type":"content_block_delta","delta":{"thinking":"secret"}}\n\ndata: {"type":"message_delta","usage":{"output_tokens":12}}\n\ndata: {"type":"message_stop"}\n\n',
    ]),
  );
  await (
    await a.host.fetch("/api/backends/chat-completions/generate", request)
  ).text();
  assert.equal(a.records[1].inputTokens, 17);
  assert.equal(a.records[1].outputTokens, 12);
  assert.equal(a.records[1].result, "success");
  const g = fixture(() =>
    sse([
      'data: {"candidates":[{"content":{"parts":[{"text":"secret"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":11,"candidatesTokenCount":7}}\n\n',
    ]),
  );
  await (
    await g.host.fetch("/api/backends/chat-completions/generate", request)
  ).text();
  assert.equal(g.records[1].outputTokens, 7);
  assert.equal(g.records[1].result, "success");
  await g.host.fetch("/api/settings/save", { method: "POST", body: "{}" });
  assert.equal(g.records.length, 2);
  let upstream = 0;
  const host = {
    location: new URL("http://tavern.invalid"),
    fetch: async () => {
      upstream++;
      return new Response("{}");
    },
  };
  observeRpCalls(
    host,
    () => null,
    () => assert.fail("unconfigured"),
    () => {},
  );
  await host.fetch("/api/backends/chat-completions/generate", request);
  assert.equal(upstream, 1);
});

class MemoryStorage {
  map = new Map();
  get length() {
    return this.map.size;
  }
  key(i) {
    return [...this.map.keys()][i] ?? null;
  }
  getItem(k) {
    return this.map.get(k) ?? null;
  }
  setItem(k, v) {
    this.map.set(k, v);
  }
  removeItem(k) {
    this.map.delete(k);
  }
}
test("offline queue survives and pending acknowledgements cannot remove newer final results", async () => {
  const storage = new MemoryStorage(),
    settings = { url: "http://center", token: "rp", device: "fn:user" };
  let offline = true,
    release;
  const seen = [];
  const outbox = new RpCallOutbox(
    () => settings,
    async (_path, body) => {
      seen.push(structuredClone(body));
      if (offline) throw Error("offline");
      if (body.events[0].result === "pending")
        await new Promise((r) => (release = r));
      return { acknowledgedIds: [body.events[0].eventId] };
    },
    storage,
    () => {},
  );
  const pending = {
    eventId: "one",
    model: "native",
    origin: "live",
    result: "pending",
    occurredAt: new Date().toISOString(),
    isStream: true,
  };
  outbox.put(pending);
  while (outbox.delivering) await new Promise((r) => setImmediate(r));
  assert.equal(storage.length, 1);
  offline = false;
  const delivering = outbox.deliver();
  while (!release) await new Promise((r) => setImmediate(r));
  outbox.put({ ...pending, result: "success", inputTokens: 5 });
  release();
  await delivering;
  while (outbox.delivering) await new Promise((r) => setImmediate(r));
  assert.equal(storage.length, 0);
  assert.equal(seen.at(-1).events[0].result, "success");
});
