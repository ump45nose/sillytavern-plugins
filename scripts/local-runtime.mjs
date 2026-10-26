// Docker-free local runtime: official release + isolated data + deterministic model on 127.0.0.1.
// Usage: node scripts/local-runtime.mjs prepare|start|stop|status
// Mirrors compose.yaml ports so every verify:* script works unchanged against localhost.
import { execFileSync, spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const lock = JSON.parse(fs.readFileSync(path.join(root, "baseline.lock.json"), "utf8"));
const upstream = path.join(root, "upstream", "SillyTavern");
const runtime = path.join(root, "runtime");
const pidFile = path.join(runtime, "local-pids.json");
const envPath = path.join(root, ".env");
// visual: a disposable instance reseeded for screenshot baselines (scripts/visual/*).
// WB_PORT_OFFSET (environment or .env) shifts every port so a second checkout can run beside the first.
const offset = Number(process.env.WB_PORT_OFFSET ?? readEnv().WB_PORT_OFFSET ?? 0);
const instances = { baseline: 32011 + offset, validation: 32012 + offset, visual: 32014 + offset };
const mockPort = 32013 + offset;
// WB_BIND_ADDRESS (e.g. 0.0.0.0 for tailnet / LAN) applies to the workbench instances; baseline stays on loopback.
const exposed = ["validation", "visual"];
// The workbench instances load server plug-ins (workbench-sync for IDE sync); baseline stays official.
const withPlugins = ["validation", "visual"];

function readEnv() {
  if (!fs.existsSync(envPath)) return {};
  return Object.fromEntries(
    fs.readFileSync(envPath, "utf8").split("\n")
      .filter((line) => line.includes("=") && !line.startsWith("#"))
      .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]),
  );
}

function prepare() {
  if (!fs.existsSync(upstream)) {
    execFileSync("git", ["clone", "--depth", "1", "--branch", lock.upstream.release, lock.upstream.repository, upstream], { stdio: "inherit" });
  }
  const commit = execFileSync("git", ["-C", upstream, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  if (commit !== lock.upstream.commit) throw new Error("Upstream checkout differs from baseline.lock.json; refusing to prepare.");
  if (!fs.existsSync(path.join(upstream, "node_modules"))) {
    execFileSync("npm", ["ci", "--omit=dev", "--no-audit", "--no-fund"], { cwd: upstream, stdio: "inherit" });
  }
  if (!fs.existsSync(envPath)) {
    // Test-only credentials for the localhost instances; never reuse elsewhere.
    fs.writeFileSync(envPath, [
      "WB_BIND_ADDRESS=127.0.0.1",
      "WB_USERNAME=workbench",
      `WB_PASSWORD=${crypto.randomBytes(18).toString("base64url")}`,
      `WB_MOCK_API=http://127.0.0.1:${mockPort}/v1`,
      ...(offset ? [`WB_PORT_OFFSET=${offset}`] : []),
      "",
    ].join("\n"), { mode: 0o600 });
  }
  const env = readEnv();
  for (const [name, port] of Object.entries(instances)) {
    const directory = path.join(runtime, name);
    for (const sub of ["config", "data/default-user/extensions", "backups"]) fs.mkdirSync(path.join(directory, sub), { recursive: true });
    const config = path.join(directory, "config/config.yaml");
    if (!fs.existsSync(config)) {
      fs.writeFileSync(config, `dataRoot: ${JSON.stringify(path.join(directory, "data"))}
listen: false
listenAddress:
  ipv4: 127.0.0.1
port: ${port}
browserLaunch:
  enabled: false
whitelistMode: false
basicAuthMode: true
basicAuthUser:
  username: ${JSON.stringify(env.WB_USERNAME)}
  password: ${JSON.stringify(env.WB_PASSWORD)}
enableUserAccounts: false
enableServerPlugins: ${withPlugins.includes(name)}
enableServerPluginsAutoUpdate: false
extensions:
  enabled: true
  autoUpdate: false
  models:
    autoDownload: false
`, { mode: 0o600 });
    }
    const settingsPath = path.join(directory, "data/default-user/settings.json");
    if (!fs.existsSync(settingsPath)) {
      const settings = JSON.parse(fs.readFileSync(path.join(upstream, "default/content/settings.json"), "utf8"));
      settings.firstRun = false;
      settings.main_api = "openai";
      Object.assign(settings.oai_settings, {
        chat_completion_source: "custom",
        custom_url: env.WB_MOCK_API,
        custom_model: "workbench-fixture",
        stream_openai: true,
      });
      settings.extension_settings.disabledExtensions = [];
      settings.extension_settings.notifyUpdates = false;
      settings.enableAutoUpdate = false;
      fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    }
  }
  linkExtensions();
  const helperSource = process.env.WB_HELPER_SOURCE;
  const helperTarget = path.join(runtime, "validation/data/default-user/extensions/JS-Slash-Runner");
  if (!fs.existsSync(helperTarget)) {
    if (helperSource && fs.existsSync(path.join(helperSource, "manifest.json"))) {
      const manifest = JSON.parse(fs.readFileSync(path.join(helperSource, "manifest.json"), "utf8"));
      if (manifest.version !== lock.helper.version) throw new Error(`Helper ${manifest.version} differs from locked ${lock.helper.version}.`);
      fs.mkdirSync(helperTarget, { recursive: true });
      for (const sub of ["dist", "lib", "i18n"]) fs.cpSync(path.join(helperSource, sub), path.join(helperTarget, sub), { recursive: true });
      for (const file of ["manifest.json", "LICENSE"]) fs.copyFileSync(path.join(helperSource, file), path.join(helperTarget, file));
    } else {
      console.warn("JS-Slash-Runner not installed: set WB_HELPER_SOURCE to the locked helper assets; helper checks will be skipped.");
    }
  }
  console.log(`Prepared official ${lock.upstream.release} (${commit.slice(0, 12)}) on 127.0.0.1:${Object.values(instances).join("/")}.`);
}

// Validation and visual instances load this checkout's extensions as user-scoped third-party extensions.
// Also run on start, so runtimes prepared before wb-perf existed pick it up.
function linkExtensions() {
  const links = { "workbench-probe": "extension", "wb-perf": "perf-extension" };
  for (const name of ["validation", "visual"])
    for (const [id, source] of Object.entries(links)) {
      const target = path.join(runtime, name, "data/default-user/extensions", id);
      if (!fs.existsSync(target)) fs.symlinkSync(path.join(root, source), target, "dir");
    }
}

// Re-applied on every start so changing WB_BIND_ADDRESS, the credentials in .env or the plug-in switch needs no reprepare;
// SillyTavern keeps these keys when it rewrites the file.
function applyEnv(name) {
  const env = readEnv();
  const config = path.join(runtime, name, "config/config.yaml");
  const address = exposed.includes(name) ? env.WB_BIND_ADDRESS || "127.0.0.1" : "127.0.0.1";
  const keys = [
    [/^listen: .*$/m, `listen: ${address !== "127.0.0.1"}`],
    [/^(listenAddress:\n  ipv4: ).*$/m, `$1${address}`],
    [/^(basicAuthUser:\n  username: ).*$/m, `$1${JSON.stringify(env.WB_USERNAME)}`],
    [/^(basicAuthUser:\n  username: .*\n  password: ).*$/m, `$1${JSON.stringify(env.WB_PASSWORD)}`],
    [/^enableServerPlugins: .*$/m, `enableServerPlugins: ${withPlugins.includes(name)}`],
  ];
  let text = fs.readFileSync(config, "utf8");
  for (const [pattern, value] of keys) {
    if (!pattern.test(text)) throw new Error(`${config} lacks ${pattern.source}`);
    text = text.replace(pattern, value);
  }
  fs.writeFileSync(config, text, { mode: 0o600 });
  return address;
}

function running() {
  if (!fs.existsSync(pidFile)) return {};
  const pids = JSON.parse(fs.readFileSync(pidFile, "utf8"));
  return Object.fromEntries(Object.entries(pids).filter(([, pid]) => {
    try { process.kill(pid, 0); return true; } catch { return false; }
  }));
}

function launch(name, command, args, options) {
  const log = fs.openSync(path.join(runtime, `${name}.log`), "a");
  const child = spawn(command, args, { ...options, detached: true, stdio: ["ignore", log, log] });
  child.unref();
  return child.pid;
}

async function waitFor(url, headers) {
  for (let i = 0; i < 120; i++) {
    try {
      const response = await fetch(url, { headers });
      if ([200, 401].includes(response.status)) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function start() {
  if (!fs.existsSync(path.join(runtime, "validation/config/config.yaml"))) prepare();
  linkExtensions();
  const pids = running();
  if (!pids.mock) pids.mock = launch("mock", process.execPath, [path.join(root, "fixtures/mock-model.mjs")], { env: { ...process.env, PORT: String(mockPort), HOST: "127.0.0.1" } });
  const only = process.argv.slice(3).filter((arg) => !arg.startsWith("--"));
  for (const [name] of Object.entries(instances)) {
    if (only.length && !only.includes(name)) continue;
    if (!pids[name]) {
      console.log(`${name} listens on ${applyEnv(name)}:${instances[name]}`);
      pids[name] = launch(name, process.execPath, ["server.js", "--configPath", path.join(runtime, name, "config/config.yaml")], { cwd: upstream, env: { ...process.env, NODE_ENV: "production" } });
    }
  }
  fs.writeFileSync(pidFile, JSON.stringify(pids, null, 2));
  for (const [name, port] of Object.entries(instances)) if (pids[name]) await waitFor(`http://127.0.0.1:${port}/`);
  console.log("Running:", Object.entries(pids).map(([name, pid]) => `${name}(${pid})`).join(", "));
}

function stop(only = []) {
  const pids = running();
  for (const [name, pid] of Object.entries(pids)) {
    if (only.length && !only.includes(name)) continue;
    try { process.kill(-pid, "SIGTERM"); } catch { try { process.kill(pid, "SIGTERM"); } catch {} }
    console.log(`Stopped ${name}`);
    delete pids[name];
  }
  if (Object.keys(pids).length) fs.writeFileSync(pidFile, JSON.stringify(pids, null, 2));
  else fs.rmSync(pidFile, { force: true });
}

// Recreate the visual instance from scratch so screenshot baselines start from identical data.
// Extensions installed by hand (e.g. the database plug-in) are kept; verifier sessions disable them.
async function resetVisual() {
  stop(["visual"]);
  await new Promise((resolve) => setTimeout(resolve, 800));
  const extensions = path.join(runtime, "visual/data/default-user/extensions"), kept = path.join(runtime, "visual-extensions");
  fs.rmSync(kept, { recursive: true, force: true });
  if (fs.existsSync(extensions)) fs.renameSync(extensions, kept);
  fs.rmSync(path.join(runtime, "visual"), { recursive: true, force: true });
  prepare();
  for (const name of fs.existsSync(kept) ? fs.readdirSync(kept) : []) {
    if (!fs.existsSync(path.join(extensions, name))) fs.renameSync(path.join(kept, name), path.join(extensions, name));
  }
  fs.rmSync(kept, { recursive: true, force: true });
  process.argv = [process.argv[0], process.argv[1], "start", "visual"];
  await start();
}

const command = process.argv[2];
if (command === "prepare") prepare();
else if (command === "start") await start();
else if (command === "stop") stop(process.argv.slice(3));
else if (command === "reset-visual") await resetVisual();
else if (command === "status") console.log(running());
else console.log("Usage: node scripts/local-runtime.mjs prepare | start [instance...] | stop [instance...] | reset-visual | status");
