"use strict";
// Protocol adapted from Rewards v4.3.2 (GPL-3.0-or-later):
// BrowserFunc.getAppDashboardData and activities/app/{DailyCheckIn,AppReward,ReadToEarn}.
const { randomUUID, randomBytes } = require("node:crypto");
const fs = require("node:fs"),
  path = require("node:path");
const { boundedJson } = require("./browser_common.cjs");
// Daily/read actions expire with their business day. Keep just one bounded day;
// multi-day promotions continue to use their separate reconciliation journal.
function dailyJournal(stateDir, businessDate) {
  if (
    typeof businessDate !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(businessDate) ||
    !Number.isFinite(Date.parse(businessDate)) ||
    new Date(businessDate).toISOString().slice(0, 10) !== businessDate
  )
    throw Error("business_date_invalid");
  const keys = [
    "daily_" + businessDate,
    ...Array.from({ length: 10 }, (_, i) => `read_${businessDate}_${i}`),
  ];
  const file = path.join(stateDir, "app-daily-journal.json");
  let entries = {};
  if (fs.existsSync(file)) {
    const saved = boundedJson(file, 65536);
    if (
      saved?.schema_version !== 1 ||
      typeof saved.business_date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(saved.business_date) ||
      !saved.entries ||
      Array.isArray(saved.entries) ||
      typeof saved.entries !== "object" ||
      Object.keys(saved.entries).length > 11 ||
      Object.values(saved.entries).some(
        (v) => !["attempted", "confirmed"].includes(v),
      )
    )
      throw Error("journal_invalid");
    if (saved.business_date > businessDate)
      throw Error("business_date_regressed");
    if (saved.business_date === businessDate) {
      if (Object.keys(saved.entries).some((key) => !keys.includes(key)))
        throw Error("journal_invalid");
      entries = saved.entries;
    }
  }
  // Preserve existing current-day intent during migration, without altering the
  // old promotion/uncertain-action journal or importing obsolete day keys.
  const legacy = path.join(stateDir, "app-journal.json");
  if (fs.existsSync(legacy)) {
    const saved = boundedJson(legacy, 65536);
    if (
      !saved ||
      Array.isArray(saved) ||
      typeof saved !== "object" ||
      Object.keys(saved).length > 100 ||
      Object.values(saved).some((v) => !["attempted", "confirmed"].includes(v))
    )
      throw Error("journal_invalid");
    for (const key of keys)
      if (Object.hasOwn(saved, key)) entries[key] = saved[key];
  }
  return {
    has: (key) => Object.hasOwn(entries, key),
    async mark(key, status) {
      if (!keys.includes(key) || !["attempted", "confirmed"].includes(status))
        throw Error("journal_invalid");
      entries[key] = status;
      const temporary = file + ".tmp";
      fs.writeFileSync(
        temporary,
        JSON.stringify({
          schema_version: 1,
          business_date: businessDate,
          entries,
        }),
        { mode: 0o600 },
      );
      fs.renameSync(temporary, file);
    },
  };
}
const ORIGIN = "https://prod.rewardsplatform.microsoft.com";
const UA =
  "Bing/32.5.431027001 (com.microsoft.bing; build:431027001; iOS 17.6.1) Alamofire/5.10.2";
class AuthenticationRequired extends Error {
  constructor(reason) {
    super(reason);
    this.name = "AppAuthenticationRequired";
  }
}
function createClient({
  token,
  country,
  language,
  fetchImpl = globalThis.fetch,
}) {
  if (
    typeof token !== "string" ||
    token.length < 1 ||
    token.length > 16384 ||
    /[\r\n]/.test(token)
  )
    throw new AuthenticationRequired("app_token_missing");
  if (
    !/^[A-Za-z]{2}$/.test(country) ||
    !/^[A-Za-z]{2}(?:-[A-Za-z]{2})?$/.test(language)
  )
    throw Error("app_locale_invalid");
  async function send(route, body) {
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 20000);
    try {
      const headers = {
        Authorization: `Bearer ${token}`,
        "User-Agent": UA,
        "X-Rewards-Country": country,
        "X-Rewards-Language": language,
        "X-Rewards-IsMobile": "true",
      };
      if (body) headers["Content-Type"] = "application/json";
      if (body?.type === 103)
        Object.assign(headers, {
          "X-Rewards-AppId": "SAIOS/33.4.440603001",
          "X-Rewards-PartnerId": "startapp",
          "X-Rewards-Flights": "rwgobig",
          "User-Agent":
            "Mozilla/5.0 (iPad; CPU iPad OS 26_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/605.1.15 BingSapphire/33.4.440603001",
        });
      const response = await fetchImpl(ORIGIN + route, {
        method: body ? "POST" : "GET",
        headers,
        body: body ? JSON.stringify(body) : undefined,
        redirect: "error",
        signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403)
        throw new AuthenticationRequired("app_token_expired_or_scope_changed");
      if (response.status === 429) throw Error("app_rate_limited");
      if (response.status !== 200) throw Error("app_response_unavailable");
      const reader = response.body?.getReader();
      if (!reader) throw Error("app_response_unavailable");
      let size = 0,
        text = "";
      const decoder = new TextDecoder();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 1048576) throw Error("app_response_too_large");
          text += decoder.decode(value, { stream: true });
        }
        text += decoder.decode();
      } finally {
        await reader.cancel().catch(() => {});
      }
      return JSON.parse(text);
    } finally {
      clearTimeout(timer);
    }
  }
  return {
    read: () => send("/dapi/me?channel=SAIOS&options=613"),
    submit(kind, offerId) {
      if (!["daily", "promotion", "read"].includes(kind))
        throw Error("app_capability_invalid");
      if (
        kind !== "daily" &&
        (typeof offerId !== "string" || !/^[A-Za-z0-9_-]{1,200}$/.test(offerId))
      )
        throw Error("app_offer_invalid");
      const body =
        kind === "daily"
          ? {
              risk_context: {},
              type: 103,
              channel: "SAIOS",
              attributes: {},
              id: randomUUID(),
              amount: 1,
              country,
            }
          : {
              id:
                kind === "read"
                  ? randomBytes(64).toString("hex")
                  : randomUUID(),
              amount: 1,
              type: 101,
              attributes: { offerid: offerId },
              country,
            };
      return send("/dapi/me/activities", body);
    },
  };
}
function promotions(raw) {
  const response = raw?.response;
  if (
    typeof response?.profile?.ruid !== "string" ||
    !response.profile.ruid ||
    !Number.isFinite(response.balance) ||
    response.balance < 0 ||
    !Array.isArray(response.promotions) ||
    response.promotions.length > 300
  )
    throw Error("app_inventory_unavailable");
  const selected = response.promotions.filter(
    (p) => p?.attributes?.type === "sapphire",
  );
  if (selected.length > 40) throw Error("app_inventory_limit");
  const ids = new Set();
  return selected.map((p) => {
    const a = p.attributes,
      id = a.offerid;
    if (
      typeof id !== "string" ||
      !/^[A-Za-z0-9_-]{1,200}$/.test(id) ||
      ids.has(id)
    )
      throw Error("app_offer_invalid");
    ids.add(id);
    return {
      id,
      complete:
        typeof a.complete === "string"
          ? a.complete.toLowerCase() === "true"
            ? true
            : a.complete.toLowerCase() === "false"
              ? false
              : null
          : null,
    };
  });
}
async function runPromotions(
  client,
  journal,
  { wait = () => new Promise((resolve) => setTimeout(resolve, 5000)) } = {},
) {
  const rows = promotions(await client.read()),
    results = [];
  for (const row of rows) {
    if (row.complete === true) {
      results.push("complete");
      continue;
    }
    if (row.complete !== false || journal.has(row.id)) {
      results.push("unknown");
      continue;
    }
    await journal.mark(row.id, "attempted");
    let uncertain = false;
    try {
      await client.submit("promotion", row.id);
    } catch (error) {
      if (
        error instanceof AuthenticationRequired ||
        error.message === "app_rate_limited"
      )
        throw error;
      uncertain = true;
    }
    let complete = false;
    for (let i = 0; i < 3; i++) {
      try {
        complete =
          promotions(await client.read()).find((p) => p.id === row.id)
            ?.complete === true;
      } catch (error) {
        if (
          error instanceof AuthenticationRequired ||
          error.message === "app_rate_limited"
        )
          throw error;
      }
      if (complete) break;
      if (i < 2) await wait();
    }
    if (complete) await journal.mark(row.id, "confirmed");
    results.push(complete ? "complete" : "unknown");
    if (uncertain && !complete) break;
  }
  return {
    business: {
      app_promotions:
        rows.length === 0
          ? "not_applicable"
          : results.length === rows.length &&
              results.every((s) => s === "complete")
            ? "complete"
            : "unknown",
    },
  };
}
// A type-103 ACK/balance delta has no daily attribution in this upstream response.
// Keep an honest unknown until a dedicated fresh completion observation is available.
async function submitDaily(client, journal, businessDate) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate))
    throw Error("business_date_invalid");
  await client.read();
  const key = "daily_" + businessDate;
  if (journal.has(key))
    return {
      business: { app_daily: "unknown" },
      reason: "previous_daily_submission_requires_reconciliation",
    };
  await journal.mark(key, "attempted");
  try {
    await client.submit("daily");
  } catch (error) {
    if (
      error instanceof AuthenticationRequired ||
      error.message === "app_rate_limited"
    )
      throw error;
  }
  await client.read();
  return {
    business: { app_daily: "unknown" },
    reason: "daily_submitted_without_attributable_confirmation",
  };
}
module.exports = {
  dailyJournal,
  createClient,
  promotions,
  runPromotions,
  submitDaily,
  AuthenticationRequired,
};

// Source ReadToEarn used ten type-101 submissions, stopping on no credit.
// Fresh offer eligibility is required here, and uncertain writes stop the loop.
async function readToEarn(
  client,
  journal,
  businessDate,
  {
    maxArticles = 10,
    wait = () => new Promise((r) => setTimeout(r, 30000)),
  } = {},
) {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(businessDate) ||
    !Number.isInteger(maxArticles) ||
    maxArticles < 1 ||
    maxArticles > 10
  )
    throw Error("read_budget_invalid");
  const offer = "ENUS_readarticle3_30points";
  let submitted = 0;
  function observe(raw) {
    const response = raw?.response;
    if (
      !response?.profile?.ruid ||
      !Number.isFinite(response.balance) ||
      !Array.isArray(response.promotions) ||
      response.promotions.length > 300
    )
      throw Error("app_inventory_unavailable");
    const rows = response.promotions.filter(
      (p) => p?.attributes?.offerid === offer,
    );
    if (rows.length !== 1) throw Error("reading_offer_unavailable");
    const value =
      typeof rows[0].attributes.complete === "string"
        ? rows[0].attributes.complete.toLowerCase()
        : null;
    if (!["true", "false"].includes(value))
      throw Error("reading_eligibility_unknown");
    return { complete: value === "true", balance: response.balance };
  }
  let before = observe(await client.read());
  if (before.complete)
    return { business: { read_to_earn: "complete" }, submitted };
  for (let i = 0; i < maxArticles; i++) {
    const key = "read_" + businessDate + "_" + i;
    if (journal.has(key))
      return {
        business: { read_to_earn: "unknown" },
        submitted,
        reason: "previous_article_requires_reconciliation",
      };
    await journal.mark(key, "attempted");
    let uncertain = false;
    try {
      await client.submit("read", offer);
      submitted++;
    } catch (error) {
      if (
        error instanceof AuthenticationRequired ||
        error.message === "app_rate_limited"
      )
        throw error;
      uncertain = true;
    }
    let after = observe(await client.read());
    if (after.complete) {
      await journal.mark(key, "confirmed");
      return { business: { read_to_earn: "complete" }, submitted };
    }
    // A delta permits the source's bounded next article, but does not itself
    // prove this article or the overall capability completed.
    if (uncertain || after.balance <= before.balance)
      return {
        business: { read_to_earn: "unknown" },
        submitted,
        reason: uncertain ? "article_submission_uncertain" : "reading_stagnant",
      };
    before = after;
    if (i + 1 < maxArticles) await wait();
  }
  return {
    business: { read_to_earn: "unknown" },
    submitted,
    reason: "reading_budget_reached",
  };
}
module.exports.readToEarn = readToEarn;
