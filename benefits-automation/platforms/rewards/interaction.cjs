"use strict";
// Bounded, sequential reading and input pacing. Journals remain before writes.
const trace = require("./telemetry.cjs");
const DEFAULTS = Object.freeze({enabled: true, stage: [2000,5000], action: [1500,3500],
  reading: [10000,15000], settle: [1200,2800], typing: [40,110],
  searchJitter: [0,12000], batch: [45000,75000], breakEvery: 8});
function configuration(value = {}) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).some(k => !Object.hasOwn(DEFAULTS, k))) throw Error("invalid_interaction_config");
  const config = {...DEFAULTS, ...value};
  if (typeof config.enabled !== "boolean" || !Number.isInteger(config.breakEvery) || config.breakEvery < 1 || config.breakEvery > 20)
    throw Error("invalid_interaction_config");
  for (const key of ["stage", "action", "reading", "settle", "typing", "searchJitter", "batch"])
    if (!Array.isArray(config[key]) || config[key].length !== 2 ||
      config[key].some(n => !Number.isInteger(n) || n < 0 || n > (key === "typing" ? 500 : 120000)) ||
      config[key][0] > config[key][1]) throw Error("invalid_interaction_config");
  return config;
}
function create(value, {random = Math.random, sleep = ms => new Promise(resolve => setTimeout(resolve, ms))} = {}) {
  const config = configuration(value);
  function sample(range) {
    const r = random();
    if (!Number.isFinite(r) || r < 0 || r >= 1) throw Error("invalid_interaction_random");
    return range[0] + Math.floor(r * (range[1]-range[0]+1));
  }
  async function delay(page, kind, ms) {
    if (ms <= 0) return;
    await trace.span(kind === "batch" ? "interaction.batch_break" : "interaction.pause", {kind, delay_ms: ms},
      () => page ? page.waitForTimeout(ms) : sleep(ms));
  }
  async function pause(page, kind, minimum = 0) {
    const range = config[kind];
    if (!range) throw Error("invalid_interaction_config");
    const ms = config.enabled ? Math.max(minimum, range[0]) + sample([0,range[1]-range[0]]) : minimum;
    await delay(page, kind, ms);
  }
  return {
    config, pause,
    async type(page, box, text) {
      await pause(page, "action");
      await trace.span("interaction.type", {characters: [...text].length}, async () => {
        if (config.enabled && typeof box.pressSequentially === "function") {
          await box.click();
          await box.fill("");
          for (const character of text) await box.pressSequentially(character, {delay: sample(config.typing)});
        } else await box.fill(text);
      });
    },
    async click(page, control, options = {}) {
      await control.scrollIntoViewIfNeeded?.();
      await pause(page, "action");
      return trace.span("interaction.click", {}, () => control.click({...options,
        ...(config.enabled ? {delay: sample([80,180])} : {})}));
    },
    async review(page, minimum = 0) {
      await trace.span("interaction.review", {}, async () => {
        if (config.enabled && typeof page.mouse?.wheel === "function") await page.mouse.wheel(0, sample([240,480]));
        await pause(page, "reading", minimum);
      });
    },
    async cooldown(page, base = 30000) {
      if (!Number.isInteger(base) || base < 0 || base > 300000) throw Error("invalid_search_config");
      await delay(page, "search", config.enabled ? Math.max(30000,base) + sample(config.searchJitter) : base);
    },
    async rest(page, performed) {
      if (config.enabled && performed > 0 && performed % config.breakEvery === 0) await pause(page, "batch");
    },
  };
}
module.exports = {DEFAULTS, configuration, create};
