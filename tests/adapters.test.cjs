const test = require("node:test"),
  assert = require("node:assert/strict");
const smzdm = require("../platforms/smzdm/adapter.cjs");
const laowang = require("../platforms/laowang/adapter.cjs");
test("SMZDM missing credentials makes no request", async () =>
  assert.equal(
    (
      await smzdm.run(
        () => {
          throw Error("called");
        },
        "",
        "",
      )
    ).reason,
    "missing_session",
  ));
test("SMZDM confirmed sign remains separate from unknown reward", async () => {
  let calls = [];
  const fake = async (p) => {
    calls.push(p);
    return p === "/checkin" ? { payload: { error_code: 0 } } : { payload: {} };
  };
  const r = await smzdm.run(fake, "sess=synthetic; device_id=x", "");
  assert.equal(r.business.checkin, "complete");
  assert.equal(r.business.reward, "unknown");
  assert.equal(calls.length, 3);
});
test("SMZDM captcha never retried", async () => {
  let n = 0;
  const r = await smzdm.run(
    async () => {
      n++;
      return { payload: { error_msg: "captcha" } };
    },
    "sess=x;device_id=y",
    "",
  );
  assert.equal(r.reason, "human_required");
  assert.equal(n, 1);
});
test("SMZDM readback exception preserves sign confirmation", async () => {
  let n = 0;
  const r = await smzdm.run(
    async () => {
      if (n++) throw Error("offline");
      return { payload: { error_code: 0 } };
    },
    "sess=x;device_id=y",
    "",
  );
  assert.equal(r.business.checkin, "complete");
  assert.equal(r.execution, "failed");
});
test("SMZDM exact signature deterministic fixture", () => {
  assert.equal(
    smzdm.signedForm({ token: "x" }, 0),
    "weixin=1&basic_v=0&f=android&v=10.4.26&time=0000&token=x&sign=EB2A2E8FCE8B2EB782D831B5C6C1AE29",
  );
});
function browser({ signed = false, challenge = false, fail = false } = {}) {
  const state = { closed: false, visits: [] };
  const page = {
    goto: async (u) => {
      state.visits.push(u);
      if (fail) throw Error("offline");
    },
    waitForTimeout: async () => {},
    locator: (selector) => ({
      count: async () =>
        selector === "#tncode" ? (challenge ? 1 : 0) : signed ? 1 : 0,
    }),
    content: async () => '<a href="formhash=abcdef12">x</a>',
  };
  return {
    state,
    firefox: {
      launchPersistentContext: async () => ({
        pages: () => [page],
        close: async () => {
          state.closed = true;
        },
      }),
    },
  };
}
test("Laowang closes browser on already complete", async () => {
  const b = browser({ signed: true });
  assert.equal((await laowang.run(b.firefox, "/fake")).checkin, "complete");
  assert.ok(b.state.closed);
});
test("Laowang challenge requires human without submission", async () => {
  const b = browser({ challenge: true });
  assert.equal(
    (await laowang.run(b.firefox, "/fake")).reason,
    "human_required",
  );
  assert.equal(b.state.visits.length, 1);
  assert.ok(b.state.closed);
});
test("Laowang closes browser on error", async () => {
  const b = browser({ fail: true });
  assert.equal((await laowang.run(b.firefox, "/fake")).execution, "failed");
  assert.ok(b.state.closed);
});
test("Laowang status does not submit", async () => {
  const b = browser();
  assert.equal(
    (await laowang.run(b.firefox, "/fake", { statusOnly: true })).checkin,
    "incomplete",
  );
  assert.equal(b.state.visits.length, 1);
});
