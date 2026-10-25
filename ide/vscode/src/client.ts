/** A SillyTavern server with the workbench-sync plug-in, as one signed-in user. */
export interface Connection {
  name: string;
  url: string;
  username: string;
}
export interface Secrets {
  password: string;
  /** workbenchSync.token on the server, when one is set. */
  token?: string;
}
export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly line?: number,
  ) {
    super(message);
  }
}
export interface Changes {
  changed: string[];
  created: string[];
  deleted: string[];
  dirs: string[];
}
export interface Status {
  pages: number;
  clients: number;
}

/**
 * Talks to /api/plugins/workbench-sync/. SillyTavern checks Basic Auth on every request and a CSRF
 * token bound to its session cookie on writes, so the client keeps the cookie from /csrf-token.
 */
export class Client {
  private session: Promise<{ cookie: string; token: string }> | undefined;
  private stream: AbortController | undefined;
  private closed = false;
  constructor(
    readonly connection: Connection,
    private secrets: Secrets,
  ) {}
  private get origin() {
    return this.connection.url.replace(/\/+$/, "");
  }
  private get auth() {
    return "Basic " + Buffer.from(`${this.connection.username}:${this.secrets.password}`).toString("base64");
  }
  private start() {
    return (this.session ??= (async () => {
      const response = await fetch(`${this.origin}/csrf-token`, { headers: { authorization: this.auth } });
      if (response.status === 401) throw new HttpError(401, "用户名或密码不正确。");
      if (!response.ok)
        throw new HttpError(response.status, `酒馆没有响应 /csrf-token（HTTP ${response.status}）。`);
      const cookie = response.headers
        .getSetCookie()
        .map((c) => c.split(";")[0])
        .join("; ");
      return { cookie, token: String(((await response.json()) as { token?: string }).token ?? "") };
    })().catch((error) => {
      this.session = undefined;
      throw error;
    }));
  }
  private async headers() {
    const { cookie, token } = await this.start();
    return {
      authorization: this.auth,
      cookie,
      "x-csrf-token": token,
      "content-type": "application/json",
      ...(this.secrets.token ? { "x-workbench-sync-token": this.secrets.token } : {}),
    };
  }
  async request<T>(method: string, route: string, body?: unknown, retried = false): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.origin}/api/plugins/workbench-sync/${route}`, {
        method,
        headers: await this.headers(),
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      throw new HttpError(0, `无法连接酒馆：${(error as Error).message}`);
    }
    // An expired session invalidates the CSRF token: start a new one once.
    if (response.status === 403 && !retried && !(await response.clone().text()).includes("访问令牌")) {
      this.session = undefined;
      return this.request(method, route, body, true);
    }
    const text = await response.text();
    let data: any;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { error: text.slice(0, 200) };
    }
    if (response.status === 404 && !data.error)
      throw new HttpError(404, "酒馆没有加载 workbench-sync 插件。");
    if (!response.ok)
      throw new HttpError(response.status, data.error || `HTTP ${response.status}`, data.line);
    return data as T;
  }
  get = <T>(route: string, path: string) =>
    this.request<T>("GET", `${route}?path=${encodeURIComponent(path)}`);

  /** Listens to the plug-in's events until closed, reconnecting with backoff. */
  listen(handlers: {
    changes: (c: Changes) => void;
    status: (s: Status | null, error?: string) => void;
    reconnected: () => void;
  }) {
    let delay = 1000,
      first = true;
    const loop = async () => {
      while (!this.closed) {
        const abort = new AbortController();
        this.stream = abort;
        try {
          const response = await fetch(`${this.origin}/api/plugins/workbench-sync/events?role=ide`, {
            headers: await this.headers(),
            signal: abort.signal,
          });
          if (!response.ok || !response.body)
            throw new HttpError(response.status, `事件流 HTTP ${response.status}`);
          if (!first) handlers.reconnected();
          first = false;
          delay = 1000;
          const decoder = new TextDecoder();
          let buffer = "";
          for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
            buffer += decoder.decode(chunk, { stream: true });
            let end: number;
            while ((end = buffer.indexOf("\n\n")) >= 0) {
              const block = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              const event = block.match(/^event: (.*)$/m)?.[1],
                data = block.match(/^data: (.*)$/m)?.[1];
              if (!event || !data) continue;
              const payload = JSON.parse(data);
              if (event === "changed") handlers.changes(payload);
              else if (event === "hello" || event === "status") handlers.status(payload);
            }
          }
          throw new Error("事件流已结束");
        } catch (error) {
          if (this.closed) return;
          if (error instanceof HttpError && error.status === 401) this.session = undefined;
          handlers.status(null, (error as Error).message);
          await new Promise((resolve) => setTimeout(resolve, delay));
          delay = Math.min(delay * 2, 30_000);
        }
      }
    };
    void loop();
  }
  close() {
    this.closed = true;
    this.stream?.abort();
  }
}
