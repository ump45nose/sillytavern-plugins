"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const app = require("../platforms/rewards/app.cjs");
const raw = (complete) => ({
  response: {
    profile: { ruid: "synthetic-account" },
    balance: 100,
    promotions: [
      { attributes: { type: "sapphire", offerid: "offer_1", complete } },
    ],
  },
});
const journal = () => {
  const entries = new Map();
  return {
    entries,
    has: (k) => entries.has(k),
    mark: async (k, v) => entries.set(k, v),
  };
};
test("actual APP transport binds exact official URL and one request with in-memory token", async () => {
  const calls = [];
  const c = app.createClient({
    token: "synthetic",
    country: "US",
    language: "en-US",
    fetchImpl: async (...args) => {
      calls.push(args);
      return new Response(JSON.stringify(raw("false")), { status: 200 });
    },
  });
  await c.read();
  await c.submit("promotion", "offer_1");
  assert.equal(calls.length, 2);
  assert.equal(
    calls[0][0],
    "https://prod.rewardsplatform.microsoft.com/dapi/me?channel=SAIOS&options=613",
  );
  assert.equal(calls[1][1].redirect, "error");
  assert.equal(JSON.parse(calls[1][1].body).type, 101);
  assert.equal(calls[1][1].headers.Authorization, "Bearer synthetic");
});
test("missing and expired token do not trigger OAuth or retries", async () => {
  assert.throws(
    () => app.createClient({ country: "US", language: "en" }),
    /app_token_missing/,
  );
  let calls = 0;
  const c = app.createClient({
    token: "fake",
    country: "US",
    language: "en",
    fetchImpl: async () => {
      calls++;
      return new Response("", { status: 401 });
    },
  });
  await assert.rejects(c.read(), app.AuthenticationRequired);
  assert.equal(calls, 1);
});
test("promotion timeout reconciles explicit completion without replay", async () => {
  let writes = 0,
    reads = 0;
  const c = {
    read: async () => raw(++reads > 2 ? "true" : "false"),
    submit: async () => {
      writes++;
      throw Error("timeout");
    },
  };
  const j = journal();
  assert.equal(
    (await app.runPromotions(c, j, { wait: async () => {} })).business
      .app_promotions,
    "complete",
  );
  assert.equal(writes, 1);
  assert.equal(j.entries.get("offer_1"), "confirmed");
});
test("ACK or unrelated balance increase never proves offer completion", async () => {
  let writes = 0;
  const c = {
    read: async () => raw("false"),
    submit: async () => {
      writes++;
      return { response: { balance: 1000 } };
    },
  };
  const j = journal();
  assert.equal(
    (await app.runPromotions(c, j, { wait: async () => {} })).business
      .app_promotions,
    "unknown",
  );
  await app.runPromotions(c, j, { wait: async () => {} });
  assert.equal(writes, 1);
});
test("unknown complete flag, missing inventory and excessive inventories fail closed", async () => {
  const c = {
    read: async () => raw("new_enum"),
    submit: async () => assert.fail("no write"),
  };
  assert.equal(
    (await app.runPromotions(c, journal())).business.app_promotions,
    "unknown",
  );
  assert.throws(() => app.promotions({ response: {} }));
  const r = raw("false");
  r.response.promotions = Array(41).fill(r.response.promotions[0]);
  assert.throws(() => app.promotions(r), /limit/);
});
test("daily uses journal and remains unknown without attributable state", async () => {
  let writes = 0;
  const c = {
    read: async () => raw("true"),
    submit: async (kind) => {
      writes++;
      assert.equal(kind, "daily");
    },
  };
  const j = journal();
  assert.equal(
    (await app.submitDaily(c, j, "2026-10-01")).business.app_daily,
    "unknown",
  );
  await app.submitDaily(c, j, "2026-10-01");
  assert.equal(writes, 1);
});
test("rate limit stops the current promotion without retry", async () => {
  let writes = 0;
  const c = {
    read: async () => raw("false"),
    submit: async () => {
      writes++;
      throw Error("app_rate_limited");
    },
  };
  await assert.rejects(app.runPromotions(c, journal()), /rate_limited/);
  assert.equal(writes, 1);
});

test("reading preserves ten-article upper bound and does not call balance credit full completion", async () => {
  let balance = 100,
    writes = 0;
  const c = {
    read: async () => ({
      response: {
        profile: { ruid: "synthetic" },
        balance: balance++,
        promotions: [
          {
            attributes: {
              offerid: "ENUS_readarticle3_30points",
              complete: "false",
            },
          },
        ],
      },
    }),
    submit: async (kind, id) => {
      assert.equal(kind, "read");
      assert.equal(id, "ENUS_readarticle3_30points");
      writes++;
    },
  };
  const result = await app.readToEarn(c, journal(), "2026-10-01", {
    wait: async () => {},
  });
  assert.equal(writes, 10);
  assert.equal(result.business.read_to_earn, "unknown");
  assert.equal(result.reason, "reading_budget_reached");
});
test("reading stops on no credit and uncertain write with no replay", async () => {
  let writes = 0;
  const c = {
    read: async () => ({
      response: {
        profile: { ruid: "synthetic" },
        balance: 100,
        promotions: [
          {
            attributes: {
              offerid: "ENUS_readarticle3_30points",
              complete: "false",
            },
          },
        ],
      },
    }),
    submit: async () => {
      writes++;
      throw Error("timeout");
    },
  };
  const result = await app.readToEarn(c, journal(), "2026-10-01", {
    wait: async () => {},
  });
  assert.equal(writes, 1);
  assert.equal(result.reason, "article_submission_uncertain");
});
test("reading missing offer never submits", async () => {
  const c = {
    read: async () => raw("false"),
    submit: async () => assert.fail("no write"),
  };
  await assert.rejects(
    app.readToEarn(c, journal(), "2026-10-01"),
    /offer_unavailable/,
  );
});
