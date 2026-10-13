"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const fs = require("node:fs"),
  os = require("node:os"),
  path = require("node:path");
const { spawnSync } = require("node:child_process");
const { run } = require("../platforms/smzdm/adapter.cjs");
const adapter = path.resolve(__dirname, "../platforms/smzdm/adapter.cjs");
const ok = { payload: { error_code: 0 } };
const view = (flag) => ({
  payload: {
    error_code: 0,
    data: {
      rows: [
        {
          cell_type: "18001",
          cell_data: {
            checkin_continue: { continue_checkin_reward_show: flag },
          },
        },
      ],
    },
  },
});
function invoke(directory, scenario, date = "2026-10-02", confirmedPath = "") {
  const code = `
    const fs = require('node:fs');
    const calls = [];
    global.fetch = async url => {
      const p = new URL(url).pathname; calls.push(p);
      const s = JSON.parse(process.env.SCENARIO);
      if (s[p] === 'timeout') throw Error('synthetic timeout');
      return { status: 200, body: [Buffer.from(JSON.stringify(s[p] || { error_code: 0 }))] };
    };
    require(${JSON.stringify(adapter)}).main().then(() => console.log(JSON.stringify(calls)));
  `;
  const child = spawnSync(process.execPath, ["-e", code], {
    encoding: "utf8",
    env: {
      ...process.env,
      SCENARIO: JSON.stringify(scenario),
      SMZDM_COOKIE: "sess=synthetic;device_id=synthetic",
      BENEFITS_STATE_DIR: directory,
      BENEFITS_ACCOUNT: "test",
      BENEFITS_BUSINESS_DATE: date,
      BENEFITS_PLATFORM: "smzdm",
      BENEFITS_RUN_ID: "fixture",
      BENEFITS_RESULT_PATH: path.join(directory, "result.json"),
      BENEFITS_LAST_CONFIRMED_PATH: confirmedPath,
    },
  });
  assert.equal(child.signal, null, child.stderr);
  assert.ok([0, 1].includes(child.status), child.stderr);
  return {
    result: JSON.parse(fs.readFileSync(path.join(directory, "result.json"))),
    calls: JSON.parse(child.stdout),
  };
}
function fixture(t) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "smzdm-recovery-"));
  t.after(() => fs.rmSync(d, { recursive: true, force: true }));
  return d;
}
test("already signed still queries both reward endpoints and claims available extra", async () => {
  const calls = [];
  const out = await run(
    async (p) => {
      calls.push(p);
      return p === "/checkin"
        ? { payload: { error_code: 1, error_msg: "已签到" } }
        : p.endsWith("show_view_v2")
          ? view(true)
          : ok;
    },
    "sess=synthetic;device_id=x",
    "",
  );
  assert.deepEqual(calls, [
    "/checkin",
    "/checkin/all_reward",
    "/checkin/show_view_v2",
    "/checkin/extra_reward",
  ]);
  assert.deepEqual(out.business, {
    checkin: "complete",
    reward: "complete",
    extra_reward: "complete",
  });
});
test("public main across processes recovers reward queries without replaying checkin", (t) => {
  const d = fixture(t),
    scenario = {
      "/checkin/all_reward": "timeout",
      "/checkin/show_view_v2": view(false).payload,
    };
  const first = invoke(d, scenario);
  assert.equal(first.result.business.checkin, "complete");
  assert.equal(first.result.business.reward, "unknown");
  const second = invoke(d, { "/checkin/show_view_v2": view(false).payload });
  assert.deepEqual(second.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  assert.equal(second.result.business.reward, "complete");
});
test("ambiguous checkin is not replayed across processes and queries cannot prove it", (t) => {
  const d = fixture(t),
    scenario = {
      "/checkin": "timeout",
      "/checkin/show_view_v2": view(true).payload,
    };
  const first = invoke(d, scenario),
    second = invoke(d, scenario);
  assert.equal(first.calls.filter((x) => x === "/checkin").length, 1);
  assert.deepEqual(second.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  assert.equal(second.result.business.checkin, "unknown");
  assert.equal(second.result.business.extra_reward, "unknown");
});
test("ambiguous extra claim never repeats even when offer stays visible or disappears", (t) => {
  const d = fixture(t),
    scenario = {
      "/checkin/extra_reward": "timeout",
      "/checkin/show_view_v2": view(true).payload,
    };
  const first = invoke(d, scenario),
    second = invoke(d, scenario);
  assert.equal(first.result.business.checkin, "complete");
  assert.equal(first.result.business.extra_reward, "unknown");
  assert.deepEqual(second.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  const third = invoke(d, { "/checkin/show_view_v2": view(false).payload });
  assert.equal(third.result.business.extra_reward, "unknown");
});
test("confirmed extra claim is not replayed when the view lags", (t) => {
  const d = fixture(t),
    scenario = { "/checkin/show_view_v2": view(true).payload };
  assert.equal(invoke(d, scenario).result.business.extra_reward, "complete");
  const second = invoke(d, scenario);
  assert.equal(second.calls.includes("/checkin/extra_reward"), false);
  assert.equal(second.result.business.extra_reward, "complete");
});
test("a new day allows the new daily sign but retains unresolved extra claim", (t) => {
  const d = fixture(t),
    scenario = {
      "/checkin/extra_reward": "timeout",
      "/checkin/show_view_v2": view(true).payload,
    };
  invoke(d, scenario);
  const next = invoke(d, scenario, "2026-10-03");
  assert.equal(next.calls.includes("/checkin"), true);
  assert.equal(next.calls.includes("/checkin/extra_reward"), false);
});
test("legacy confirmed checkin imports only for the same account and day", (t) => {
  const d = fixture(t),
    confirmed = path.join(d, "last-confirmed.json");
  fs.writeFileSync(
    confirmed,
    JSON.stringify({
      schema_version: 1,
      run_id: "old",
      platform: "smzdm",
      account: "test",
      business_date: "2026-10-02",
      execution_status: "failed",
      reason: "reward_readback_failed",
      business: { checkin: "complete", reward: "unknown" },
    }),
  );
  const next = invoke(
    d,
    { "/checkin/show_view_v2": view(false).payload },
    "2026-10-02",
    confirmed,
  );
  assert.equal(next.calls.includes("/checkin"), false);
  assert.equal(next.result.business.reward, "complete");
});
test("corrupt journal fails closed before any HTTP request", (t) => {
  const d = fixture(t);
  fs.writeFileSync(path.join(d, "http-actions.json"), "broken");
  assert.deepEqual(invoke(d, {}).calls, []);
});

function legacyFile(directory, business, date = "2026-10-02") {
  const file = path.join(directory, "last-confirmed.json");
  fs.writeFileSync(
    file,
    JSON.stringify({
      schema_version: 1,
      run_id: "legacy",
      platform: "smzdm",
      account: "test",
      business_date: date,
      execution_status: "ok",
      reason: "sign_confirmed",
      business,
    }),
  );
  return file;
}
test("legacy extra receipt prevents repeat claim despite lagging available offer", (t) => {
  const d = fixture(t),
    confirmed = legacyFile(d, {
      checkin: "complete",
      reward: "complete",
      extra_reward: "complete",
    });
  const next = invoke(
    d,
    { "/checkin/show_view_v2": view(true).payload },
    "2026-10-02",
    confirmed,
  );
  assert.deepEqual(next.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  assert.equal(next.result.business.extra_reward, "complete");
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(d, "http-actions.json"))).extra,
    "complete",
  );
});
test("legacy extra receipt merges when journal already confirms checkin", (t) => {
  const d = fixture(t),
    confirmed = legacyFile(d, {
      checkin: "complete",
      reward: "unknown",
      extra_reward: "complete",
    });
  fs.writeFileSync(
    path.join(d, "http-actions.json"),
    JSON.stringify({
      version: 1,
      account: "test",
      date: "2026-10-02",
      checkin: "complete",
      reward: "unknown",
      extra: "unknown",
    }),
  );
  const next = invoke(
    d,
    { "/checkin/show_view_v2": view(true).payload },
    "2026-10-02",
    confirmed,
  );
  assert.deepEqual(next.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  assert.equal(next.result.business.extra_reward, "complete");
});
test("migrated receipts persist even if both reward queries fail", (t) => {
  const d = fixture(t),
    confirmed = legacyFile(d, {
      checkin: "complete",
      reward: "unknown",
      extra_reward: "complete",
    });
  invoke(
    d,
    { "/checkin/all_reward": "timeout", "/checkin/show_view_v2": "timeout" },
    "2026-10-02",
    confirmed,
  );
  const next = invoke(d, { "/checkin/show_view_v2": view(true).payload });
  assert.deepEqual(next.calls, [
    "/checkin/all_reward",
    "/checkin/show_view_v2",
  ]);
  assert.equal(next.result.business.extra_reward, "complete");
});
test("legacy checkin receipt never promotes unknown or missing extra receipt", (t) => {
  for (const business of [
    { checkin: "complete", reward: "complete", extra_reward: "unknown" },
    { checkin: "complete", reward: "unknown" },
  ]) {
    const d = fixture(t),
      confirmed = legacyFile(d, business);
    const next = invoke(
      d,
      {
        "/checkin/show_view_v2": view(true).payload,
        "/checkin/extra_reward": "timeout",
      },
      "2026-10-02",
      confirmed,
    );
    assert.equal(next.calls.includes("/checkin"), false);
    assert.equal(
      next.calls.filter((p) => p === "/checkin/extra_reward").length,
      1,
    );
    assert.equal(next.result.business.extra_reward, "unknown");
  }
});
test("legacy extra receipt does not imply checkin receipt", (t) => {
  const d = fixture(t),
    confirmed = legacyFile(d, {
      checkin: "unknown",
      reward: "unknown",
      extra_reward: "complete",
    });
  const next = invoke(
    d,
    { "/checkin": "timeout", "/checkin/show_view_v2": view(true).payload },
    "2026-10-02",
    confirmed,
  );
  assert.equal(next.calls.includes("/checkin"), true);
  assert.equal(next.calls.includes("/checkin/extra_reward"), false);
  assert.equal(next.result.business.checkin, "unknown");
  assert.equal(next.result.business.extra_reward, "complete");
});
test("previous-day legacy extra receipt does not promote today's reward", (t) => {
  const d = fixture(t),
    confirmed = legacyFile(
      d,
      { checkin: "complete", reward: "complete", extra_reward: "complete" },
      "2026-10-01",
    );
  const next = invoke(
    d,
    {
      "/checkin/show_view_v2": view(true).payload,
      "/checkin/extra_reward": "timeout",
    },
    "2026-10-02",
    confirmed,
  );
  assert.equal(next.calls.includes("/checkin"), true);
  assert.equal(next.calls.includes("/checkin/extra_reward"), true);
  assert.equal(next.result.business.extra_reward, "unknown");
});
