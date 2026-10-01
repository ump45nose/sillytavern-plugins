"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const tn = require("../platforms/laowang/tncode.cjs"),
  challenge = require("../platforms/laowang/challenge.cjs");
const { createIntent } = require("../platforms/laowang/intent.cjs"),
  { run } = require("../platforms/laowang/adapter.cjs");
function puzzle({ flat = false } = {}) {
  const width = 120,
    height = 70,
    markWidth = 40,
    offset = 53;
  const data = new Uint8ClampedArray(width * height * 3 * 4);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const i = ((y + 2 * height) * width + x) * 4;
      data[i] = flat ? 150 : 100 + ((x * 17 + y * 13) % 100);
      data[i + 1] = flat ? 150 : 100 + ((x * 11 + y * 23) % 100);
      data[i + 2] = flat ? 150 : 80 + ((x * 29 + y * 7) % 120);
      data[i + 3] = 255;
    }
  for (let y = 0; y < height; y++)
    for (let x = 0; x < markWidth; x++) {
      const a = ((y + height) * width + x) * 4,
        b = ((y + 2 * height) * width + x + offset) * 4;
      data.set(data.slice(b, b + 4), a);
    }
  return { data, width, height, markWidth, offset };
}
test("original pixel-difference matcher finds synthetic known offset", async () => {
  const p = puzzle();
  const match = await tn.analyzePuzzle(p);
  assert.equal(match.x, p.offset);
  assert.ok(match.ratio >= 1.08);
  assert.ok(match.samples >= 50);
});
test("low confidence and oversized puzzle never yield a usable answer", async () => {
  await assert.rejects(tn.analyzePuzzle(puzzle({ flat: true })), /confidence/);
  await assert.rejects(
    tn.analyzePuzzle({ data: [], width: 10000, height: 70, markWidth: 40 }),
    /dimensions/,
  );
});
test("CAPTCHA acknowledgement is exact and endpoint is official", () => {
  assert.equal(tn.accepted("_ok"), true);
  for (const s of ["not_ok", "error _ok", JSON.stringify({ secret: "_ok" })])
    assert.equal(tn.accepted(s), false);
  assert.equal(tn.checkURL("https://laowang.vip/captcha/check.php?t=1"), true);
  assert.equal(
    tn.checkURL("https://laowang.vip.evil.invalid/captcha/check.php"),
    false,
  );
});
function fakeChallenge(results = ["accepted"]) {
  const events = [];
  let loaded = 0,
    drags = 0;
  const page = {
    url: () => challenge.TARGET,
    locator: (selector) => ({ click: async () => events.push(selector) }),
    waitForFunction: async () => {},
    evaluate: async () => ({ x: 53, width: 120, markWidth: 40 }),
  };
  const options = {
    readEvidence: async () => "same-image",
    authorize: async () => null,
    loadSolver: async () => {
      loaded++;
      return {
        analyzePuzzle: () => {},
        drag: async () => {
          drags++;
          return { status: results[Math.min(drags - 1, results.length - 1)] };
        },
      };
    },
  };
  return {
    page,
    options,
    events,
    get loaded() {
      return loaded;
    },
    get drags() {
      return drags;
    },
  };
}
test("without trusted authorization no solver is loaded and no control is touched", async () => {
  const f = fakeChallenge();
  await assert.rejects(
    challenge.solve(f.page, { ...f.options, authorize: undefined }),
    challenge.PendingChallenge,
  );
  assert.equal(f.loaded, 0);
  assert.deepEqual(f.events, []);
});
test("changed challenge after authorization pauses before any activation", async () => {
  const f = fakeChallenge();
  let n = 0;
  await assert.rejects(
    challenge.solve(f.page, {
      ...f.options,
      readEvidence: async () => String(n++),
    }),
    challenge.PendingChallenge,
  );
  assert.equal(f.loaded, 0);
  assert.deepEqual(f.events, []);
});
test("approved concrete handler executes one drag and checks acceptance", async () => {
  const f = fakeChallenge();
  const result = await challenge.solve(f.page, f.options);
  assert.equal(result.status, "accepted");
  assert.equal(f.drags, 1);
  assert.equal(f.loaded, 1);
});
test("explicit rejection permits one authorized refresh; uncertain response never retries", async () => {
  const rejected = fakeChallenge(["rejected", "accepted"]);
  assert.equal(
    (await challenge.solve(rejected.page, rejected.options)).status,
    "accepted",
  );
  assert.equal(rejected.drags, 2);
  assert.deepEqual(rejected.events, ["#tncode", ".tncode_refresh"]);
  const uncertain = fakeChallenge(["unknown"]);
  assert.equal(
    (await challenge.solve(uncertain.page, uncertain.options)).status,
    "unknown",
  );
  assert.equal(uncertain.drags, 1);
  assert.deepEqual(uncertain.events, ["#tncode"]);
});
function fakeFlow({ throwSubmit = false, autoSigned = false } = {}) {
  let signed = false,
    submits = 0,
    gets = 0,
    closed = 0;
  const page = {
    url: () => challenge.TARGET,
    goto: async (u) => {
      if (u.includes("operation=qiandao")) gets++;
    },
    waitForTimeout: async () => {},
    locator: (selector) => ({
      count: async () =>
        selector === ".qdleft .btnvisted"
          ? signed
            ? 1
            : 0
          : selector === "#tncode" || selector === "#submit-btn"
            ? 1
            : 0,
      click: async () => {
        if (selector === "#submit-btn") {
          submits++;
          signed = true;
          if (throwSubmit) throw Error("timeout");
        }
      },
      first() {
        return this;
      },
      inputValue: async () => "5",
    }),
  };
  const verifier = {
    ...page,
    locator: (selector) => ({
      count: async () => (selector === ".qdleft .btnvisted" && signed ? 1 : 0),
      first() {
        return this;
      },
      inputValue: async () => "5",
    }),
    close: async () => {},
  };
  const firefox = {
    launchPersistentContext: async () => ({
      pages: () => [page],
      newPage: async () => verifier,
      close: async () => {
        closed++;
      },
    }),
  };
  const challengeOptions = {
    readEvidence: async () => "fixture",
    loadSolver: async () => ({
      analyzePuzzle: () => {},
      drag: async () => {
        if (autoSigned) signed = true;
        return { status: "accepted" };
      },
    }),
  };
  page.waitForFunction = async () => {};
  page.evaluate = async () => ({ x: 53, width: 120, markWidth: 40 });
  return {
    firefox,
    challengeOptions,
    get submits() {
      return submits;
    },
    get gets() {
      return gets;
    },
    get closed() {
      return closed;
    },
  };
}
test("uncertain sign submit reconciles confirmed status and never repeats", async () => {
  const f = fakeFlow({ throwSubmit: true });
  const out = await run(f.firefox, "/fake", {
    authorize: async () => null,
    challengeOptions: f.challengeOptions,
    intent: createIntent(null, "2026-10-01"),
  });
  assert.equal(out.checkin, "complete");
  assert.equal(f.submits, 1);
  assert.equal(f.gets, 0);
  assert.equal(f.closed, 1);
});
test("CAPTCHA acceptance that already signed is reconciled without submitting again", async () => {
  const f = fakeFlow({ autoSigned: true });
  const out = await run(f.firefox, "/fake", {
    authorize: async () => null,
    challengeOptions: f.challengeOptions,
    intent: createIntent(null, "2026-10-01"),
  });
  assert.equal(out.checkin, "complete");
  assert.equal(f.submits, 0);
});
test("prior uncertain intent permits only bounded readback", async () => {
  const f = fakeFlow(),
    intent = createIntent(null, "2026-10-01");
  intent.mark("challenge_pending");
  intent.mark("captcha_attempted");
  intent.mark("captcha_accepted");
  intent.mark("submit_attempted");
  const out = await run(f.firefox, "/fake", {
    intent,
    authorize: async () => assert.fail("not allowed"),
  });
  assert.equal(out.reason, "previous_sign_action_requires_reconciliation");
  assert.equal(f.submits, 0);
  assert.equal(f.gets, 0);
});
test("intent survives restart and resets only for another explicit business date", () => {
  const fs = require("node:fs"),
    os = require("node:os"),
    path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "laowang-intent-")),
    file = path.join(dir, "intent.json");
  try {
    createIntent(file, "2026-10-01").mark("request_attempted");
    assert.equal(createIntent(file, "2026-10-01").requestAttempted, true);
    assert.equal(createIntent(file, "2026-10-02").requestAttempted, false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("missing or malformed page origin is never replaced with a trusted site", () => {
  for (const page of [
    {},
    { url: () => undefined },
    { url: () => "https://evil.invalid/plugin.php" },
    { url: () => "https://laowang.vip:8443/plugin.php" },
  ])
    assert.throws(() => challenge.safeTarget(page));
});
test("concrete slider binding listens before release and validates exact server response", async () => {
  let listening = false,
    downs = 0,
    ups = 0,
    moves = 0;
  const page = {
    locator: () => ({
      count: async () => 1,
      boundingBox: async () => ({ x: 0, y: 0, width: 20, height: 20 }),
    }),
    mouse: {
      move: async () => {
        moves++;
      },
      down: async () => {
        downs++;
      },
      up: async () => {
        assert.equal(listening, true);
        ups++;
      },
    },
    waitForTimeout: async () => {},
    waitForResponse: async (predicate) => {
      listening = true;
      assert.equal(
        predicate({ url: () => "https://evil.invalid/captcha/check.php" }),
        false,
      );
      assert.equal(
        predicate({ url: () => "https://laowang.vip/captcha/check.php" }),
        true,
      );
      return {
        headers: () => ({ "content-length": "3" }),
        text: async () => "_ok",
      };
    },
  };
  assert.equal(
    (await tn.drag(page, { x: 53, width: 120, markWidth: 40 })).status,
    "accepted",
  );
  assert.equal(downs, 1);
  assert.equal(ups, 1);
  assert.equal(moves, 33);
});
test("concrete slider response with unknown size does not read arbitrary body", async () => {
  const page = {
    locator: () => ({
      count: async () => 1,
      boundingBox: async () => ({ x: 0, y: 0, width: 20, height: 20 }),
    }),
    mouse: { move: async () => {}, down: async () => {}, up: async () => {} },
    waitForTimeout: async () => {},
    waitForResponse: async () => ({
      headers: () => ({}),
      text: async () => assert.fail("unbounded body"),
    }),
  };
  assert.equal(
    (await tn.drag(page, { x: 53, width: 120, markWidth: 40 })).status,
    "unknown",
  );
});

test("persisted approval pause resumes fresh visible challenge without replaying qiandao", async () => {
  const fs = require("node:fs"),
    os = require("node:os"),
    path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "laowang-resume-")),
    file = path.join(dir, "intent.json");
  try {
    const first = fakeFlow();
    const paused = await run(first.firefox, "/fake", {
      intent: createIntent(file, "2026-10-01"),
      challengeOptions: first.challengeOptions,
    });
    assert.equal(paused.reason, "human_required");
    assert.equal(createIntent(file, "2026-10-01").phase, "challenge_pending");
    const resumed = fakeFlow();
    const done = await run(resumed.firefox, "/fake", {
      intent: createIntent(file, "2026-10-01"),
      authorize: async () => null,
      challengeOptions: resumed.challengeOptions,
    });
    assert.equal(done.checkin, "complete");
    assert.equal(resumed.gets, 0);
    assert.equal(resumed.submits, 1);
    assert.equal(createIntent(file, "2026-10-01").phase, "submit_attempted");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
test("uncertain prior drag cannot be repeated after restart", async () => {
  const f = fakeFlow(),
    intent = createIntent(null, "2026-10-01");
  intent.mark("challenge_pending");
  intent.mark("captcha_attempted");
  const out = await run(f.firefox, "/fake", {
    intent,
    authorize: async () => assert.fail("no replay"),
  });
  assert.equal(out.reason, "previous_sign_action_requires_reconciliation");
  assert.equal(f.submits, 0);
  assert.equal(f.gets, 0);
});

test("two-drag budget survives reopening the intent journal", () => {
  const fs = require("node:fs"),
    os = require("node:os"),
    path = require("node:path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "laowang-budget-")),
    file = path.join(dir, "intent.json");
  try {
    const intent = createIntent(file, "2026-10-01");
    intent.mark("challenge_pending");
    for (let i = 0; i < 2; i++) {
      intent.mark("captcha_attempted");
      intent.mark("captcha_rejected");
    }
    const reopened = createIntent(file, "2026-10-01");
    assert.equal(reopened.attempts, 2);
    assert.throws(() => reopened.mark("captcha_attempted"), /attempt_limit/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
