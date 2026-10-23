#!/usr/bin/env node
/**
 * 将当前 Mac 上已闭合的 Skysight 片段和派生摘要幂等同步到 NAS。
 * 使用 ChatGPT 自带 Node 运行时，以继承 OpenAI Skysight 应用组读取权限。
 */

import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/** 仅表示输入校验失败；网络和权限异常不得进入内容隔离。 */
export class SegmentValidationError extends Error {}

const home = os.homedir();
const defaults = {
  source: path.join(
    home,
    "Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/Library/Caches/ComputerUse/Skysight/segments",
  ),
  checkpoint: path.join(
    home,
    "Library/Application Support/PersonalReview/skysight-checkpoint.json",
  ),
  host: process.env.SKYSIGHT_SSH_HOST || "yuwk-201",
  target:
    process.env.SKYSIGHT_RAW_TARGET ||
    "/vol2/1000/Docker/personal-review/data/raw/skysight",
  derivedSource: path.join(
    home,
    ".codex/memories/extensions/skysight/resources",
  ),
  derivedTarget:
    process.env.SKYSIGHT_DERIVED_TARGET ||
    "/vol2/1000/Docker/personal-review/data/derived/skysight/source-summaries",
  hubCli: process.env.SKYSIGHT_HUB_CLI || "/home/yuwk/code/personal-data-hub/.venv/bin/hub",
  timezone: process.env.SKYSIGHT_TIMEZONE || "Asia/Shanghai",
};

/** 解析少量显式参数；环境变量负责安装后的固定配置。 */
function parseArguments(argv) {
  const args = { ...defaults, dryRun: false, repairCountMismatch: false };
  const names = new Map([
    ["--source", "source"],
    ["--checkpoint", "checkpoint"],
    ["--host", "host"],
    ["--target", "target"],
    ["--derived-source", "derivedSource"],
    ["--derived-target", "derivedTarget"],
    ["--timezone", "timezone"],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--dry-run") {
      args.dryRun = true;
      continue;
    }
    if (token === "--repair-count-mismatch") {
      args.repairCountMismatch = true;
      continue;
    }
    const name = names.get(token);
    if (!name || !argv[index + 1]) {
      throw new Error(`未知或缺少参数值: ${token}`);
    }
    args[name] = argv[index + 1];
    index += 1;
  }
  return args;
}

/** 为 SSH 的远程 shell 参数保留字面值。 */
function remoteCommand(tokens) {
  return tokens.map((value) => "'" + String(value).replaceAll("'", "'\"'\"'") + "'").join(" ");
}

/** NAS 在文件校验和数据库提交之后回执，失败时 Mac 不推进游标。 */
function acknowledge(args, source, relative, expectedHash, execute) {
  execute("/usr/bin/ssh", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host,
    remoteCommand([args.hubCli, "ack-skysight", "--source", source, "--relative", relative, "--expected-hash", expectedHash])], args.dryRun);
}

/** 读取 checkpoint；结构异常时拒绝从头同步，防止大规模重复上传。 */
function loadCheckpoint(checkpointPath) {
  if (!fs.existsSync(checkpointPath)) {
    return {
      schema_version: 1,
      segments: {},
      summaries: {},
      invalid_segments: {},
    };
  }
  const value = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
  if (value.schema_version !== 1 || typeof value.segments !== "object") {
    throw new Error("checkpoint 结构不兼容");
  }
  value.summaries ||= {};
  value.invalid_segments ||= {};
  return value;
}

/** 原子保存 checkpoint，避免断电留下半写 JSON。 */
function saveCheckpoint(checkpointPath, value) {
  fs.mkdirSync(path.dirname(checkpointPath), { recursive: true });
  const temporary = `${checkpointPath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, {
    mode: 0o600,
  });
  fs.renameSync(temporary, checkpointPath);
}

/** 按文件名和内容顺序计算组合哈希，用于识别闭合片段的后续修正。 */
function digestFiles(files) {
  const hasher = crypto.createHash("sha256");
  for (const file of files) {
    hasher.update(path.basename(file));
    hasher.update(fs.readFileSync(file));
  }
  return hasher.digest("hex");
}

/** 校验片段已经闭合且事件行数与 metadata 一致。 */
export function validateSegment(directory, options = {}) {
  const metadataPath = path.join(directory, "metadata.json");
  const eventsPath = path.join(directory, "events.jsonl");
  if (!fs.existsSync(metadataPath) || !fs.existsSync(eventsPath)) {
    return null;
  }
  // 上传必须使用同一次读取的快照；不能先校验再复制正在变化的源文件。
  const files = [metadataPath, eventsPath];
  const before = files.map((file) => fs.statSync(file));
  const sourceMetadata = fs.readFileSync(metadataPath);
  const events = fs.readFileSync(eventsPath);
  const after = files.map((file) => fs.statSync(file));
  if (before.some((value, index) => value.size !== after[index].size || value.mtimeMs !== after[index].mtimeMs)) {
    return null;
  }
  let metadata;
  try {
    metadata = JSON.parse(sourceMetadata.toString("utf8"));
  } catch {
    throw new SegmentValidationError(`${path.basename(directory)} metadata_json_invalid`);
  }
  if (metadata.endedAt == null) {
    return null;
  }
  const started = Date.parse(metadata.startedAt);
  const ended = Date.parse(metadata.endedAt);
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) {
    throw new SegmentValidationError(`${path.basename(directory)} metadata_time_invalid`);
  }
  const lines = events.toString("utf8").split("\n");
  if (lines.at(-1) === "") lines.pop();
  const records = [];
  for (const [index, line] of lines.entries()) {
    try {
      records.push(JSON.parse(line));
    } catch {
      // JSON.parse 的原始异常可能含事件正文；只记录位置和错误类别。
      throw new SegmentValidationError(`${path.basename(directory)} events_json_invalid line=${index + 1}`);
    }
  }
  let repair = null;
  if (Number.isInteger(metadata.eventCount) && metadata.eventCount !== lines.length) {
    if (!options.repairCountMismatch) {
      throw new SegmentValidationError(`${path.basename(directory)} event_count_mismatch expected=${metadata.eventCount} actual=${lines.length}`);
    }
    const now = options.now ?? Date.now();
    const stableAgeMs = (options.stableAgeSeconds ?? 120) * 1000;
    if (now - ended < stableAgeMs || after.some((value) => now - value.mtimeMs < stableAgeMs)) {
      return null;
    }
    // 只修复稳定闭合、所有事件均在区间内的计数滞后；不删事件或改正文。
    if (records.some((record) => {
      const timestamp = typeof record?.timestamp === "string" ? Date.parse(record.timestamp) : NaN;
      return !Number.isFinite(timestamp) || timestamp < started || timestamp > ended;
    })) {
      throw new SegmentValidationError(`${path.basename(directory)} repair_rejected_event_time`);
    }
    repair = {
      schema_version: 1,
      reason: "stable_closed_segment_event_count_mismatch",
      source_event_count: metadata.eventCount,
      actual_event_count: lines.length,
      source_metadata_sha256: crypto.createHash("sha256").update(sourceMetadata).digest("hex"),
      events_sha256: crypto.createHash("sha256").update(events).digest("hex"),
      repaired_at: new Date(now).toISOString(),
    };
    metadata = { ...metadata, eventCount: lines.length };
  }
  const hasher = crypto.createHash("sha256");
  hasher.update("metadata.json").update(sourceMetadata).update("events.jsonl").update(events);
  return {
    metadata,
    digest: hasher.digest("hex"),
    sourceMetadata,
    events,
    metadataBytes: repair ? Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`) : sourceMetadata,
    repair,
  };
}

/** 返回片段输入哈希；文件尚不完整时返回 null。 */
function segmentInputDigest(directory) {
  const files = [
    path.join(directory, "metadata.json"),
    path.join(directory, "events.jsonl"),
  ];
  return files.every((file) => fs.existsSync(file)) ? digestFiles(files) : null;
}

/** 执行无 shell 拼接的外部命令，避免路径和参数被二次解释。 */
function run(command, args, dryRun) {
  if (dryRun) {
    process.stdout.write(`${JSON.stringify({ dry_run: [command, ...args] })}\n`);
    return;
  }
  const result = spawnSync(command, args, { encoding: "utf8", timeout: 120000 });
  if (result.status !== 0) {
    throw new Error(`${command} command_failed status=${result.status} code=${result.error?.code || "nonzero_exit"}`);
  }
}

/** 将 ISO 时间转换为指定时区的 YYYY-MM-DD 业务日期。 */
function businessDay(isoTime, timezone) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(isoTime));
}

/** 先用有应用组权限的 Node 暂存片段，再调用 rsync，避免 rsync 本身被 TCC 拒绝。 */
export function syncSegment(args, directory, result, execute = run) {
  const { metadata } = result;
  const name = path.basename(directory);
  if (!name.endsWith("Z") || !args.target.includes("/raw/skysight")) {
    throw new Error("拒绝使用不安全的片段名或 NAS 目标");
  }
  const day = businessDay(metadata.startedAt, args.timezone);
  const remoteParent = `${args.target}/${day}`;
  const remoteFinal = `${remoteParent}/${name}`;
  execute("/usr/bin/ssh", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, remoteCommand(["mkdir", "-p", remoteParent])], args.dryRun);
  if (args.dryRun) {
    execute("/usr/bin/rsync", ["-a", "--delay-updates", `${directory}/`, `${args.host}:${remoteFinal}/`], true);
    return;
  }

  const cacheRoot = path.join(home, "Library/Caches/PersonalReview");
  fs.mkdirSync(cacheRoot, { recursive: true });
  const staging = fs.mkdtempSync(path.join(cacheRoot, "skysight-"));
  const stagedDirectory = path.join(staging, name);
  try {
    fs.mkdirSync(stagedDirectory);
    // Skysight 闭合片段的交付契约只有这两个文件；逐文件复制可避开
    // macOS 对仍由生产进程维护的目录执行递归 directory_iterator 时偶发 EINTR。
    fs.writeFileSync(path.join(stagedDirectory, "metadata.json"), result.metadataBytes, { mode: 0o600 });
    fs.writeFileSync(path.join(stagedDirectory, "events.jsonl"), result.events, { mode: 0o600 });
    fs.writeFileSync(path.join(stagedDirectory, "hub-manifest.json"), JSON.stringify({schema_version: 1, source_digest: result.digest, files: [{name: "metadata.json", sha256: crypto.createHash("sha256").update(result.metadataBytes).digest("hex")}, {name: "events.jsonl", sha256: crypto.createHash("sha256").update(result.events).digest("hex")}]}), {mode: 0o600});
    if (result.repair) {
      // 修复仅发生在交付副本；保留原始 metadata 与校验记录供审计。
      fs.writeFileSync(path.join(stagedDirectory, "metadata.source.json"), result.sourceMetadata, { mode: 0o600 });
      fs.writeFileSync(path.join(stagedDirectory, "sync-validation.json"), `${JSON.stringify(result.repair, null, 2)}\n`, { mode: 0o600 });
    }
    execute(
      "/usr/bin/rsync",
      ["-a", "--delay-updates", "--timeout=60", "-e", "/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=10", `${stagedDirectory}/`, `${args.host}:${remoteFinal}/`],
      false,
    );
    acknowledge(args, "skysight-raw", `${day}/${name}/metadata.json`, result.digest, execute);
  } finally {
    // 暂存目录可能包含屏幕事件，完成或失败后都必须立即删除。
    fs.rmSync(staging, { recursive: true, force: true });
  }
}

/** 增量同步 Computer History 已生成的 10 分钟和 6 小时摘要。 */
function syncSummaries(args, checkpoint, execute = run) {
  if (!fs.existsSync(args.derivedSource)) {
    return 0;
  }
  let changed = 0;
  const names = fs
    .readdirSync(args.derivedSource)
    .filter((name) => name.endsWith("-memory-summary.md"))
    .filter((name) => name.includes("10min") || name.includes("6h"))
    .sort();
  for (const name of names) {
    const source = path.join(args.derivedSource, name);
    const digest = digestFiles([source]);
    if (checkpoint.summaries[name] === digest) {
      continue;
    }
    execute("/usr/bin/ssh", ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, remoteCommand(["mkdir", "-p", args.derivedTarget])], args.dryRun);
    execute("/usr/bin/rsync", ["-a", "--timeout=60", "-e", "/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=10", source, `${args.host}:${args.derivedTarget}/${name}`], args.dryRun);
    acknowledge(args, "skysight-summaries", name, digest, execute);
    if (!args.dryRun) {
      checkpoint.summaries[name] = digest;
    }
    changed += 1;
  }
  return changed;
}

/** 执行一次同步并输出不含原始内容的统计结果。 */
export function main(argv = process.argv.slice(2), execute = run) {
  const args = parseArguments(argv);
  const checkpoint = loadCheckpoint(args.checkpoint);
  let synced = 0;
  let skippedMutable = 0;
  let segmentErrors = 0;
  let quarantinedSkipped = 0;
  let repairedSynced = 0;
  let summaryErrors = 0;

  let summaries = 0;
  try {
    summaries = syncSummaries(args, checkpoint, execute);
  } catch (error) {
    // 摘要上传失败不能阻断原始片段；不写摘要成功时间，下一轮继续重试。
    summaryErrors += 1;
    process.stderr.write(`summary_sync_failed ${error?.code || error?.constructor?.name || "Error"}\n`);
  }
  if (!args.dryRun) {
    if (summaryErrors === 0) checkpoint.last_summary_success_at = new Date().toISOString();
    // 摘要批次中先前成功的文件也要保留进度，失败文件下一轮继续重试。
    saveCheckpoint(args.checkpoint, checkpoint);
  }

  const directories = fs
    .readdirSync(args.source, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(args.source, entry.name))
    .sort();
  for (const directory of directories) {
    const name = path.basename(directory);
    let inputDigest = null;
    try {
      inputDigest = segmentInputDigest(directory);
      if (
        inputDigest != null &&
        checkpoint.invalid_segments[name] === inputDigest && !args.repairCountMismatch
      ) {
        quarantinedSkipped += 1;
        continue;
      }
      const result = validateSegment(directory, args);
      if (result == null) {
        skippedMutable += 1;
        continue;
      }
      if (checkpoint.segments[name] === result.digest) {
        continue;
      }
      syncSegment(args, directory, result, execute);
      if (!args.dryRun) {
        checkpoint.segments[name] = result.digest;
        delete checkpoint.invalid_segments[name];
        saveCheckpoint(args.checkpoint, checkpoint);
      }
      synced += 1;
      if (result.repair) repairedSynced += 1;
    } catch (error) {
      // 单个坏片段留在源端等待后续修正，不阻断其余闭合片段。
      segmentErrors += 1;
      if (!args.dryRun && inputDigest != null && error instanceof SegmentValidationError) {
        // 同一内容只报告一次；哈希变化后会自动退出隔离并重新校验。
        checkpoint.invalid_segments[name] = inputDigest;
        saveCheckpoint(args.checkpoint, checkpoint);
      }
      process.stderr.write(`${error instanceof SegmentValidationError ? error.message : `${name} ${error?.code || error?.constructor?.name || "Error"}`}\n`);
    }
  }

  const status = segmentErrors > 0 || summaryErrors > 0 || quarantinedSkipped > 0 ? "partial" : "ok";
  if (!args.dryRun) {
    checkpoint.last_attempt_at = new Date().toISOString();
    if (status === "ok") {
      checkpoint.last_success_at = checkpoint.last_attempt_at;
      checkpoint.last_complete_success_at = checkpoint.last_attempt_at;
    }
    saveCheckpoint(args.checkpoint, checkpoint);
  }
  const summaryFiles = fs.existsSync(args.derivedSource)
    ? fs.readdirSync(args.derivedSource).filter((name) => name.endsWith("-memory-summary.md") && (name.includes("10min") || name.includes("6h"))).sort()
    : [];
  const newestSummary = summaryFiles.at(-1);
  const summaryMtime = newestSummary ? fs.statSync(path.join(args.derivedSource, newestSummary)).mtimeMs : null;
  process.stdout.write(
    `${JSON.stringify({
      status,
      segments_synced: synced,
      mutable_skipped: skippedMutable,
      segment_errors: segmentErrors,
      quarantined_skipped: quarantinedSkipped,
      summaries_synced: summaries,
      summary_errors: summaryErrors,
      repaired_segments_synced: repairedSynced,
      summary_source_latest: newestSummary || null,
      summary_source_status: summaryMtime === null ? "missing" : Date.now() - summaryMtime > 6 * 3600000 ? "stale" : "fresh",
    })}\n`,
  );
  return status === "partial" ? 2 : 0;
}

// 导入测试模块时不得自动触发真实 SSH 或写入生产检查点。
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main();
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ status: "error", type: error?.constructor?.name || "Error", code: error?.code || null })}\n`);
    process.exitCode = 2;
  }
}
