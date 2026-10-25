import * as vscode from "vscode";
import { Client, HttpError, type Connection, type Status } from "./client";

const SCHEME = "sillytavern",
  STORE = "workbenchSync.connections";
const secretKey = (name: string, kind: "password" | "token") => `workbenchSync:${name}:${kind}`;
const encoder = new TextEncoder(),
  decoder = new TextDecoder();

/**
 * sillytavern://<连接名>/世界书/… : SillyTavern's data as files, served by the workbench-sync
 * plug-in. Every read renders from SillyTavern; every save goes back through the plug-in, which
 * writes via the open workbench page or straight to disk.
 */
class TavernFileSystem implements vscode.FileSystemProvider {
  private emitter = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
  readonly onDidChangeFile = this.emitter.event;
  /** The version each file was last read or written at; saves send it as their base. */
  private versions = new Map<string, string>();
  /** Files whose stored text differs from what was saved (defaults filled in): reloaded after the save. */
  readonly normalized = new Set<string>();
  constructor(
    private clients: Map<string, Client>,
    private connect: (name: string) => Promise<Client>,
    private diagnostics: vscode.DiagnosticCollection,
    private onConflict: (name: string) => void,
  ) {}
  private async client(uri: vscode.Uri) {
    return this.clients.get(uri.authority) ?? this.connect(uri.authority);
  }
  private static path(uri: vscode.Uri) {
    return uri.path.replace(/^\/+|\/+$/g, "");
  }
  fire(events: vscode.FileChangeEvent[]) {
    if (events.length) this.emitter.fire(events);
  }
  private failure(uri: vscode.Uri, error: unknown): never {
    if (!(error instanceof HttpError)) throw error;
    if (error.status === 404) throw vscode.FileSystemError.FileNotFound(uri);
    if (error.status === 405) throw vscode.FileSystemError.NoPermissions(error.message);
    if (error.status === 409) this.onConflict(uri.authority);
    throw vscode.FileSystemError.Unavailable(error.message);
  }
  watch(): vscode.Disposable {
    // Changes arrive on the plug-in's event stream for every file at once.
    return new vscode.Disposable(() => {});
  }
  async stat(uri: vscode.Uri): Promise<vscode.FileStat> {
    try {
      // The version is not recorded here: VS Code stats a dirty file after a change event, and the
      // save must still carry the version the editor's text was read at.
      const stat = await (
        await this.client(uri)
      ).get<{ type: "file" | "dir"; mtime: number; size: number }>("stat", TavernFileSystem.path(uri));
      return {
        type: stat.type === "dir" ? vscode.FileType.Directory : vscode.FileType.File,
        ctime: 0,
        mtime: stat.mtime,
        size: stat.size,
      };
    } catch (error) {
      this.failure(uri, error);
    }
  }
  async readDirectory(uri: vscode.Uri): Promise<[string, vscode.FileType][]> {
    try {
      const { entries } = await (
        await this.client(uri)
      ).get<{ entries: { name: string; type: string }[] }>("tree", TavernFileSystem.path(uri));
      return entries.map((e) => [
        e.name,
        e.type === "dir" ? vscode.FileType.Directory : vscode.FileType.File,
      ]);
    } catch (error) {
      this.failure(uri, error);
    }
  }
  async readFile(uri: vscode.Uri): Promise<Uint8Array> {
    try {
      const file = await (
        await this.client(uri)
      ).get<{ text: string; version: string }>("file", TavernFileSystem.path(uri));
      this.versions.set(uri.toString(), file.version);
      return encoder.encode(file.text);
    } catch (error) {
      this.failure(uri, error);
    }
  }
  async writeFile(uri: vscode.Uri, content: Uint8Array, options: { create: boolean; overwrite: boolean }) {
    const key = uri.toString(),
      base = this.versions.get(key) ?? "";
    if (!base && !options.create) throw vscode.FileSystemError.FileNotFound(uri);
    try {
      const result = await (
        await this.client(uri)
      ).request<{ version?: string; normalized: boolean }>("PUT", "file", {
        path: TavernFileSystem.path(uri),
        text: decoder.decode(content),
        base,
      });
      this.diagnostics.delete(uri);
      if (result.version) this.versions.set(key, result.version);
      else this.versions.delete(key);
      if (result.normalized) this.normalized.add(key);
    } catch (error) {
      if (error instanceof HttpError && error.status === 422) {
        const line = Math.max(0, (error.line ?? 1) - 1);
        this.diagnostics.set(uri, [
          new vscode.Diagnostic(
            new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER),
            error.message,
            vscode.DiagnosticSeverity.Error,
          ),
        ]);
        throw vscode.FileSystemError.Unavailable(
          `${error.line ? `第 ${error.line} 行：` : ""}${error.message}`,
        );
      }
      this.failure(uri, error);
    }
  }
  async delete(uri: vscode.Uri) {
    try {
      await (
        await this.client(uri)
      ).request("POST", "delete", {
        path: TavernFileSystem.path(uri),
        base: this.versions.get(uri.toString()) ?? "",
      });
      this.versions.delete(uri.toString());
    } catch (error) {
      this.failure(uri, error);
    }
  }
  async rename(from: vscode.Uri, to: vscode.Uri) {
    try {
      const { version } = await (
        await this.client(from)
      ).request<{ version?: string }>("POST", "rename", {
        from: TavernFileSystem.path(from),
        to: TavernFileSystem.path(to),
      });
      this.versions.delete(from.toString());
      if (version) this.versions.set(to.toString(), version);
    } catch (error) {
      this.failure(from, error);
    }
  }
  createDirectory(): void {
    throw vscode.FileSystemError.NoPermissions("目录由酒馆的数据决定；新建资源请在酒馆中操作。");
  }
}

/** The connect command's answers; scripts may pass them as the command argument instead of answering prompts. */
interface ConnectArgs {
  name: string;
  url: string;
  username: string;
  password: string;
  token?: string;
  /** Add sillytavern://<name>/ as a workspace folder (default true). */
  folder?: boolean;
}
async function ask(): Promise<ConnectArgs | undefined> {
  const url = await vscode.window.showInputBox({
    title: "连接酒馆（1/4）",
    prompt: "酒馆地址；公网请用 HTTPS（Basic Auth 在 HTTP 上是明文）",
    value: "http://127.0.0.1:8000",
    validateInput: (v) => (/^https?:\/\/[^/]+/.test(v) ? undefined : "以 http:// 或 https:// 开头"),
  });
  if (!url) return;
  const username = await vscode.window.showInputBox({
    title: "连接酒馆（2/4）",
    prompt: "用户名（config.yaml 的 basicAuthUser）",
  });
  if (username === undefined) return;
  const password = await vscode.window.showInputBox({
    title: "连接酒馆（3/4）",
    prompt: "密码（存入 VS Code 的 SecretStorage）",
    password: true,
  });
  if (password === undefined) return;
  const token = await vscode.window.showInputBox({
    title: "连接酒馆（4/4）",
    prompt: "访问令牌（服务端设置了 workbenchSync.token 时填写，否则留空）",
    password: true,
  });
  if (token === undefined) return;
  const name = await vscode.window.showInputBox({
    title: "连接名称",
    prompt: "显示在 sillytavern://<名称>/ 中",
    value: "tavern",
    validateInput: (v) => (/^[a-z0-9][a-z0-9-]*$/i.test(v) ? undefined : "只用字母、数字和 -"),
  });
  if (!name) return;
  return { name, url, username, password, token };
}

export function activate(context: vscode.ExtensionContext) {
  const clients = new Map<string, Client>(),
    states = new Map<string, { status: Status | null; error?: string; conflict?: number }>(),
    diagnostics = vscode.languages.createDiagnosticCollection("酒馆同步"),
    bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  const connections = () => context.globalState.get<Connection[]>(STORE, []);
  const render = () => {
    const entries = [...states];
    if (!entries.length) return bar.hide();
    const [name, state] = entries[0],
      conflict = state.conflict && Date.now() - state.conflict < 15_000;
    bar.text = conflict
      ? "$(warning) 酒馆：冲突"
      : !state.status
        ? "$(debug-disconnect) 酒馆：未连接"
        : state.status.pages
          ? "$(plug) 酒馆：经页面中转"
          : "$(plug) 酒馆：直写磁盘";
    bar.tooltip = conflict
      ? "文件已在酒馆中修改：重新载入或比较后再保存。"
      : !state.status
        ? `${name}：${state.error ?? "正在连接"}`
        : `${name} · 已连接 · ${state.status.pages ? "保存经已打开的工作台页面写入" : "没有打开的工作台页面，保存直接写入酒馆数据文件"}`;
    bar.show();
  };
  const fs = new TavernFileSystem(
    clients,
    (name) => open(name),
    diagnostics,
    (name) => {
      const state = states.get(name);
      if (state) state.conflict = Date.now();
      render();
      setTimeout(render, 15_500);
    },
  );
  async function open(name: string) {
    const existing = clients.get(name);
    if (existing) return existing;
    const connection = connections().find((c) => c.name === name);
    const password = await context.secrets.get(secretKey(name, "password"));
    if (!connection || password === undefined)
      throw vscode.FileSystemError.Unavailable(`没有名为「${name}」的酒馆连接：请运行「连接酒馆」。`);
    const client = new Client(connection, {
      password,
      token: (await context.secrets.get(secretKey(name, "token"))) || undefined,
    });
    clients.set(name, client);
    states.set(name, { status: null });
    const uri = (path: string) => vscode.Uri.from({ scheme: SCHEME, authority: name, path: "/" + path });
    client.listen({
      changes: (c) =>
        fs.fire([
          ...c.changed.map((p) => ({ type: vscode.FileChangeType.Changed, uri: uri(p) })),
          ...c.created.map((p) => ({ type: vscode.FileChangeType.Created, uri: uri(p) })),
          ...c.deleted.map((p) => ({ type: vscode.FileChangeType.Deleted, uri: uri(p) })),
          ...c.dirs.map((p) => ({ type: vscode.FileChangeType.Changed, uri: uri(p) })),
        ]),
      status: (status, error) => {
        states.set(name, { ...states.get(name), status, error });
        render();
      },
      // Events may have been missed while away: everything may have changed.
      reconnected: () => fs.fire([{ type: vscode.FileChangeType.Changed, uri: uri("") }]),
    });
    render();
    return client;
  }
  function close(name: string) {
    clients.get(name)?.close();
    clients.delete(name);
    states.delete(name);
    render();
  }

  context.subscriptions.push(
    diagnostics,
    bar,
    vscode.workspace.registerFileSystemProvider(SCHEME, fs, { isCaseSensitive: true }),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const key = doc.uri.toString();
      if (!fs.normalized.delete(key)) return;
      // Show the text as SillyTavern stored it (for example a new entry's uid and defaults).
      if (vscode.window.activeTextEditor?.document === doc)
        void vscode.commands.executeCommand("workbench.action.files.revert");
    }),
    vscode.commands.registerCommand("workbenchSync.connect", async (preset?: ConnectArgs) => {
      const answers = preset ?? (await ask());
      if (!answers) return false;
      const { name, url, username, password, token = "", folder = true } = answers;
      const connection = { name, url: url.replace(/\/+$/, ""), username };
      const probe = new Client(connection, { password, token: token || undefined });
      try {
        await probe.request("GET", "info");
      } catch (error) {
        void vscode.window.showErrorMessage(`连接失败：${(error as Error).message}`);
        return false;
      }
      close(name);
      await context.globalState.update(STORE, [...connections().filter((c) => c.name !== name), connection]);
      await context.secrets.store(secretKey(name, "password"), password);
      if (token) await context.secrets.store(secretKey(name, "token"), token);
      else await context.secrets.delete(secretKey(name, "token"));
      await open(name);
      const root = vscode.Uri.from({ scheme: SCHEME, authority: name, path: "/" });
      const folders = vscode.workspace.workspaceFolders ?? [];
      if (folder && !folders.some((f) => f.uri.toString() === root.toString()))
        vscode.workspace.updateWorkspaceFolders(folders.length, 0, { uri: root, name: `酒馆 · ${name}` });
      return true;
    }),
    vscode.commands.registerCommand("workbenchSync.disconnect", async () => {
      const name = await vscode.window.showQuickPick(
        connections().map((c) => c.name),
        { title: "断开酒馆" },
      );
      if (!name) return;
      close(name);
      await context.globalState.update(
        STORE,
        connections().filter((c) => c.name !== name),
      );
      await context.secrets.delete(secretKey(name, "password"));
      await context.secrets.delete(secretKey(name, "token"));
      const index = (vscode.workspace.workspaceFolders ?? []).findIndex(
        (f) => f.uri.scheme === SCHEME && f.uri.authority === name,
      );
      if (index >= 0) vscode.workspace.updateWorkspaceFolders(index, 1);
    }),
    { dispose: () => [...clients.keys()].forEach(close) },
  );
  // Folders from an earlier session reconnect when VS Code first reads them.
}

export function deactivate() {}
