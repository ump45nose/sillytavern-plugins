const common = require('/home/yuwk/benefits-automation/platforms/rewards/browser_common.cjs');
const fs = require('fs');
const report = {requests: []};
const safeError = e => ({name: e.name, timeout: /Timeout/i.test(e.name),
  code: /ERR_[A-Z_]+/.exec(e.message)?.[0] || (/flyout_[a-z_]+/.exec(e.message)?.[0] || 'unclassified')});
(async () => {
  try {
    await common.withBrowser(common.dependency('/home/yuwk/benefits-automation/platforms/rewards'),
      common.readState('/vol2/1000/Docker/benefits-automation/acceptance-20261003/state/rewards/default'),
      {proxy: 'http://192.168.31.201:7890'}, async (context, page) => {
        page.on('requestfailed', r => {
          if (report.requests.length < 5) report.requests.push({host: new URL(r.url()).hostname,
            code: r.failure()?.errorText.match(/ERR_[A-Z_]+/)?.[0] || 'failed'});
        });
        await page.goto(common.DASHBOARD, {waitUntil: 'domcontentloaded', timeout: 45000});
        report.host = new URL(page.url()).hostname;
        await common.guard(page);
        report.guarded = true;
        report.progressbars = await page.getByRole('progressbar').evaluateAll(xs => xs.slice(0,12).map(x => ({
          label: x.getAttribute('aria-label'), current:x.getAttribute('aria-valuenow'), max:x.getAttribute('aria-valuemax')})));
        try {
          const raw = await common.readFlyout(context);
          report.flyout = {isError: raw.isError, isRewardsUser: raw.userInfo?.isRewardsUser,
            flyoutUser:raw.flyoutResult?.userStatus?.isRewardsUser, hasCounters:!!raw.flyoutResult?.userStatus?.counters};
        } catch(e) {report.flyoutError=safeError(e);}
      });
  } catch(e) {report.error = safeError(e);}
  fs.writeFileSync('/home/yuwk/benefits-review/acceptance-20261003/rewards-readonly.json', JSON.stringify(report), {mode:0o600});
  console.log(JSON.stringify(report));
})().catch(() => process.exitCode = 1);
