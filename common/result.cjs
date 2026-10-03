"use strict";
const fs = require("node:fs"),
  path = require("node:path");
const {validateDetails} = require("./details.cjs");
function publish(execution, reason, business, details = {metrics: {}, items: []}) {
  const result = {
    schema_version: 1,
    run_id: process.env.BENEFITS_RUN_ID,
    platform: process.env.BENEFITS_PLATFORM,
    account: process.env.BENEFITS_ACCOUNT,
    business_date: process.env.BENEFITS_BUSINESS_DATE,
    execution_status: execution,
    reason,
    business,
    details: validateDetails(details),
  };
  const destination = process.env.BENEFITS_RESULT_PATH;
  const temp = destination + ".tmp-" + process.pid;
  fs.writeFileSync(temp, JSON.stringify(result), { mode: 0o600, flag: "wx" });
  fs.renameSync(temp, destination);
  process.exitCode = execution === "ok" ? 0 : 1;
  return result;
}
module.exports = { publish };
