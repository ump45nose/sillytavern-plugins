// 部署工作台到 fn 生产（192.168.31.201:32001）：构建 → 门禁 → 前端扩展与性能扩展 rsync →
// 服务端插件比对更新（变更则重启容器）→ HTTP 探活。数据卷与凭据不触碰。
// 用法：npm run deploy [-- --skip-build|--skip-check|--no-restart|--dry]
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const flags = new Set(process.argv.slice(2));
const dry = flags.has("--dry");
const SSH = process.env.WB_DEPLOY_SSH ?? "nas";
const REMOTE_ROOT = process.env.WB_DEPLOY_ROOT ?? "/vol2/1000/Docker/sillytavern";
const CONTAINER = process.env.WB_DEPLOY_CONTAINER ?? "sillytavern";
const BASE_URL = process.env.WB_DEPLOY_URL ?? "http://192.168.31.201:32001";

const run = (cmd, args, opts = {}) => {
  console.log(`$ ${cmd} ${args.join(" ")}`);
  if (dry) return { status: 0, stdout: "" };
  return spawnSync(cmd, args, { stdio: opts.inherit ? "inherit" : "pipe", encoding: "utf8", ...opts });
};
const ssh = (cmd, opts) => run("ssh", ["-o", "BatchMode=yes", SSH, cmd], opts);
const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

if (!flags.has("--skip-build")) {
  const r = run("npm", ["run", "build"], { inherit: true });
  if (r.status !== 0) throw new Error("build 失败");
}
if (!flags.has("--skip-check")) {
  const r = run("npm", ["run", "check"], { inherit: true });
  if (r.status !== 0) throw new Error("check 门禁失败");
}

// 1) 前端扩展：整目录同步（extensions/workbench 无用户数据，--delete 安全）
const front = run("rsync", ["-a", "--delete", "extension/", `${SSH}:${REMOTE_ROOT}/extensions/workbench/`], { inherit: true });
if (front.status !== 0) throw new Error("前端扩展同步失败");
// 1b) 性能扩展：独立扩展目录 extensions/wb-perf（同样无用户数据，设置存在 settings.json 的 wbPerf 下）
const perf = run("rsync", ["-a", "--delete", "perf-extension/", `${SSH}:${REMOTE_ROOT}/extensions/wb-perf/`], { inherit: true });
if (perf.status !== 0) throw new Error("性能扩展同步失败");

// 2) 服务端插件：内容有变化才更新并重启容器
const pluginLocal = path.join(root, "server/workbench-sync/dist/index.mjs");
const localSha = sha256(fs.readFileSync(pluginLocal));
const remote = ssh(`sha256sum ${REMOTE_ROOT}/plugins/workbench-sync/index.mjs 2>/dev/null | cut -d' ' -f1`);
const remoteSha = (remote.stdout || "").trim();
let restarted = false;
if (remoteSha !== localSha) {
  console.log(`插件有变化 ${remoteSha.slice(0, 8)} -> ${localSha.slice(0, 8)}`);
  const push = run("rsync", ["-a", pluginLocal, `${SSH}:${REMOTE_ROOT}/plugins/workbench-sync/index.mjs`], { inherit: true });
  if (push.status !== 0) throw new Error("插件同步失败");
  if (flags.has("--no-restart")) {
    console.log("--no-restart：跳过重启，插件将在下次容器重启后生效（docker restart " + CONTAINER + "）");
  } else {
    const r = ssh(`docker restart ${CONTAINER}`, { inherit: true });
    if (r.status !== 0) throw new Error("容器重启失败");
    restarted = true;
  }
} else {
  console.log("插件无变化，跳过同步与重启");
}

// 3) 探活：扩展静态文件（basic auth 下 401 即在线）；插件路由（404 才代表未加载）
if (!dry) {
  const probe = async (url, ok) => {
    try {
      const res = await fetch(url);
      console.log(`${ok(res.status) ? "✓" : "✗"} ${url} -> ${res.status}`);
      return ok(res.status);
    } catch (e) {
      console.log(`✗ ${url} -> ${e.cause?.code ?? e.message}`);
      return false;
    }
  };
  // 重启后服务端要先跑完插件自动更新与加载才开始监听，等它接受连接（最多 90 s）再探
  for (let i = 0; i < 90; i++) {
    const up = await fetch(BASE_URL).then(() => true, () => false);
    if (up) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  const a = await probe(`${BASE_URL}/scripts/extensions/third-party/workbench/manifest.json`, (s) => s === 200 || s === 401);
  const p = await probe(`${BASE_URL}/scripts/extensions/third-party/wb-perf/manifest.json`, (s) => s === 200 || s === 401);
  const b = await probe(`${BASE_URL}/api/plugins/workbench-sync/info`, (s) => s !== 404);
  const c = ssh(`docker ps --filter name=^/${CONTAINER}$ --filter status=running --format '{{.Status}}'`);
  console.log(`✓ 容器: ${(c.stdout || "").trim() || "未运行!"}`);
  if (!a || !p || !b) throw new Error("探活未通过");
}
console.log(restarted ? "部署完成（容器已重启，刷新页面生效）" : "部署完成（刷新页面生效）");
