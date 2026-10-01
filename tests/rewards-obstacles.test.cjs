const test = require("node:test"),
  assert = require("node:assert/strict");
const {
  classify,
  resumePlan,
  cleanTarget,
} = require("../platforms/rewards/obstacles.cjs");
const url = "https://rewards.bing.com/earn";
test("all explicit intervention branches retain typed identity", () => {
  const expected = {
    captcha: "captcha",
    terms: "terms",
    age: "age_verification",
    login: "login",
    accountLink: "account_link",
    permission: "security_prompt",
    goal: "account_setting",
  };
  for (const [flag, kind] of Object.entries(expected)) {
    const out = classify({
      url,
      flags: { [flag]: true },
      safeEvidence: ["fixture-revision"],
    });
    assert.equal(out.kind, kind);
    assert.equal(out.fingerprint.length, 64);
    assert.equal(out.target, url);
  }
});
test("restriction takes precedence over task progress or challenge", () =>
  assert.equal(
    classify({ url, flags: { botWarning: true, captcha: true } }).code,
    "account_restricted",
  ));
test("target excludes secret query and fragment", () =>
  assert.equal(cleanTarget(url + "?token=fixture#private"), url));
test("unexpected target does not leak URL or grant a capability", () => {
  const out = classify({
    url: "https://evil.invalid/?token=fixture",
    flags: { login: true },
  });
  assert.equal(out.target, "rewards_observation");
  assert.equal(JSON.stringify(out).includes("fixture"), false);
});
test("already-completed resume reconciles without replay", () =>
  assert.equal(resumePlan(null, { completed: true }).action, "reconcile"));
test("stale page requires new checkpoint", () => {
  const observation = { url, flags: { terms: true }, safeEvidence: ["v1"] };
  const request = classify(observation);
  assert.equal(
    resumePlan(
      request,
      { ...observation, safeEvidence: ["v2"] },
      { trustedScopeResult: null },
    ).action,
    "request_new_checkpoint",
  );
});
test("grant scope validation must come from trusted caller", () => {
  const observation = {
    url,
    flags: { captcha: true },
    safeEvidence: ["fixture-challenge"],
  };
  const checkpoint = classify(observation);
  assert.equal(resumePlan(checkpoint, observation).action, "wait");
  assert.equal(
    resumePlan(checkpoint, observation, {
      trustedScopeResult: "approval_expired",
    }).action,
    "wait",
  );
  assert.equal(
    resumePlan(checkpoint, observation, { trustedScopeResult: null }).action,
    "invoke_lazy_capability",
  );
});
test("safe recovery still reprobes rather than guessing completion", () => {
  const observation = { url, flags: { networkError: true } };
  const checkpoint = classify(observation);
  assert.equal(
    resumePlan(checkpoint, observation).action,
    "bounded_safe_recovery",
  );
  assert.equal(
    resumePlan(checkpoint, { url, flags: {} }).action,
    "reprobe_business",
  );
});
test("known nonbinding cookie overlay rejects once and reads back", async () => {
  const common = require("../platforms/rewards/browser_common.cjs");
  let visible = true,
    clicks = 0;
  const page = {
    url: () => url,
    locator: (selector) => ({
      count: async () =>
        selector === "#bnp_overlay_wrapper"
          ? visible
            ? 1
            : 0
          : selector === "#bnp_btn_reject"
            ? 1
            : 0,
      isVisible: async () => visible,
      click: async () => {
        clicks++;
        visible = false;
      },
    }),
  };
  await common.guard(page);
  assert.equal(clicks, 1);
});
test("unresolved cookie overlay is explicit rather than infinite clicks", async () => {
  const common = require("../platforms/rewards/browser_common.cjs");
  let clicks = 0;
  const page = {
    url: () => url,
    locator: (selector) => ({
      count: async () =>
        ["#bnp_overlay_wrapper", "#bnp_btn_reject"].includes(selector) ? 1 : 0,
      isVisible: async () => true,
      click: async () => {
        clicks++;
        throw Error("timeout");
      },
    }),
  };
  await assert.rejects(() => common.guard(page), /cookie_notice/);
  assert.equal(clicks, 1);
});
