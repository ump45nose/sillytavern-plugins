"use strict";
// Native binding to the original private extra-activities goal flow.
// Scope is the selected goal setting only. There is no redemption/order operation.
const common = require("./browser_common.cjs");
const obstacles = require("./obstacles.cjs");
function destination(value) {
  const url = new URL(value);
  if (
    url.origin !== "https://rewards.bing.com" ||
    !/^\/redeem\/sku\/[A-Za-z0-9_-]{1,100}$/.test(url.pathname) ||
    url.search ||
    url.hash ||
    url.username ||
    url.password
  )
    throw Error("invalid_goal_destination");
  return url.href;
}
async function setManualGoal(
  page,
  { url, checkpoint, authorize, journal, guard = common.guard } = {},
) {
  const target = destination(url);
  await page.goto(target, { waitUntil: "domcontentloaded", timeout: 45000 });
  await guard(page);
  if (page.url() !== target) throw Error("goal_target_changed");
  const toggle = page.getByRole("switch", {
    name: /^(Set as your Rewards goal|设置为目标|设为目标)$/i,
  });
  if ((await toggle.count()) !== 1) throw Error("goal_control_ambiguous");
  await toggle.waitFor({ state: "attached", timeout: 20000 });
  if (await toggle.isChecked())
    return {
      business: { goal: "complete" },
      reason: "requested_goal_already_set_existing_redemption_mode_unchanged",
    };
  const observation = {
    url: target,
    flags: { goal: true },
    safeEvidence: [
      "manual-goal-setting-v1",
      target,
      "Track and manually redeem your reward",
    ],
  };
  const error = new obstacles.Obstacle(observation);
  // An integration-owned authorizer must validate authenticated consent and exact
  // common.interventions identity/fingerprint/expiry. A JSON config is not consent.
  if (
    !checkpoint ||
    typeof authorize !== "function" ||
    (await authorize(checkpoint, error.details)) !== null
  )
    throw error;
  // Reprobe after potentially interactive approval and before any changing click.
  await page.reload({ waitUntil: "domcontentloaded", timeout: 45000 });
  await guard(page);
  if (page.url() !== target) throw Error("goal_target_changed");
  if (await toggle.isChecked())
    return {
      business: { goal: "complete" },
      reason: "goal_reconciled_without_replay",
    };
  const key = "goal_" + new URL(target).pathname.split("/").pop();
  if (!journal || journal.has(key))
    return {
      business: { goal: "unknown" },
      reason: "goal_previous_action_requires_reconciliation",
    };
  const label = page
    .locator("label")
    .filter({ hasText: /^(Set as your Rewards goal|设置为目标|设为目标)$/i });
  if ((await label.count()) !== 1) throw Error("goal_control_ambiguous");
  let submitted = false;
  try {
    await label.click({ timeout: 15000 });
    const dialog = page.getByRole("dialog");
    await dialog.waitFor({ timeout: 10000 });
    if ((await dialog.count()) !== 1) throw Error("goal_dialog_ambiguous");
    await guard(page);
    const manual = dialog.getByRole("radio", {
      name: "Track and manually redeem your reward",
      exact: true,
    });
    if ((await manual.count()) !== 1) throw Error("manual_redemption_missing");
    await manual.check({ timeout: 10000 });
    if (!(await manual.isChecked()))
      throw Error("manual_redemption_not_selected");
    const next = dialog.getByRole("button", { name: "Next", exact: true });
    if ((await next.count()) !== 1) throw Error("goal_next_ambiguous");
    await guard(page);
    if (page.url() !== target) throw Error("goal_target_changed");
    // This goal wizard applies the selected mode with Next. Opening its dialog
    // and selecting the manual radio only prepare that submission. A missing
    // control therefore must not create uncertain-submission evidence.
    await journal.mark(key, "attempted");
    submitted = true;
    await next.click({ timeout: 15000 });
    await dialog
      .getByText("Your Rewards goal is set", { exact: true })
      .waitFor({ timeout: 20000 });
    const okay = dialog.getByRole("button", { name: "Okay", exact: true });
    if ((await okay.count()) === 1) await okay.click({ timeout: 10000 });
  } catch (error) {
    if (error.message === "human_required") throw error;
  }
  await page.reload({ waitUntil: "domcontentloaded", timeout: 45000 });
  await guard(page);
  if (page.url() !== target) throw Error("goal_target_changed");
  if (submitted && (await toggle.isChecked())) {
    await journal.mark(key, "confirmed");
    return {
      business: { goal: "complete" },
      reason: "manual_goal_readback_confirmed",
    };
  }
  return { business: { goal: "unknown" }, reason: "goal_update_unconfirmed" };
}
module.exports = { destination, setManualGoal };
