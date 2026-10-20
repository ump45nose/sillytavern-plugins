"use strict";
const assert = require("node:assert/strict");
const common = require("../platforms/rewards/browser_common.cjs");
const quiz = require("../platforms/rewards/daily_quiz.cjs");
const {publish} = require("../common/result.cjs");
const offerId = "Gamification_DailySet_20261020_Child2";
const quizId = "REWARDSQUIZ_ENUS_MicrosoftRewardsQuizCB_20261020";
const attempts = new Map(), selected = [];
function markup(question, summary) {
  if (question === 3) return "<main>Completed</main>";
  const links = [0,1,2].map(choice => {
    const href = "/search?filters=" + encodeURIComponent(
      `BTEPOKey:"${quizId}" BTQID:"${quizId}" BTOID:"${offerId}" BTQI:"${question}" BTCI:"${choice}"`);
    return `<a href="${href}">Choice ${choice}</a>`;
  }).join("");
  return `<style>.btom_hidden{display:none}</style><main><div class="btom_card">
    ${summary ? '<div class="btom_opts"><a href="javascript:void(0)">Previous answer</a></div>' +
      '<div class="btom_next_btn"><button onclick="this.parentElement.remove();document.querySelector(\'.btom_hidden\').className=\'\'">下一個</button></div>' : ""}
    <div class="${summary ? "btom_hidden" : ""}"><div class="btom_opts">${links}</div>
    <div class="btq_prog"><div class="btq_lbl">${question+1}/3</div></div></div></div></main>`;
}
(async () => {
  await common.withBrowser(common.dependency(process.env.REWARDS_ROOT), {cookies: [], origins: []}, {},
    async (context, page) => {
      await context.route("**/*", async route => {
        const url = new URL(route.request().url());
        assert.equal(url.hostname, "www.bing.com");
        const answer = quiz.answer(url.href, offerId);
        if (answer) selected.push([answer.question, answer.choice]);
        await route.fulfill({contentType: "text/html", body: markup(answer ? answer.question+1 : 0, Boolean(answer))});
      });
      await page.goto("https://www.bing.com/search?q=fixture");
      await quiz.finish(page, {offerId}, {
        journal: {has: key => attempts.has(key), mark: async (key, state) => attempts.set(key, state)},
        guard: common.guard, pacing: {pause: async () => {}, review: async () => {}},
      });
      assert.deepEqual(selected, [[0,0],[1,0],[2,0]]);
      assert.equal(attempts.size, 3);
    });
  publish("ok", "quiz_browser_smoke_passed", {quiz_smoke: "complete"});
})().catch(error => {
  console.error(error.stack);
  publish("failed", "quiz_browser_smoke_failed", {quiz_smoke: "unknown"});
});
