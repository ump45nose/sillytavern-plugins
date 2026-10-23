"use strict";
const fs = require("node:fs");
const {writeJson} = require("../../common/atomic_json.cjs");
const {boundedJson} = require("./browser_common.cjs");
function journal(file) {
  let rows = {};
  if (fs.existsSync(file)) rows = boundedJson(file, 65536);
  if (
    !rows ||
    Array.isArray(rows) ||
    typeof rows !== "object" ||
    Object.keys(rows).length > 100 ||
    Object.values(rows).some((v) => !["attempted", "confirmed"].includes(v))
  )
    throw Error("journal_invalid");
  return {
    has: (id) => Object.hasOwn(rows, id),
    async mark(id, status) {
      if (
        !/^[A-Za-z0-9_-]{1,200}$/.test(id) ||
        (Object.keys(rows).length >= 100 && !Object.hasOwn(rows, id))
      )
        throw Error("journal_limit");
      if (!["attempted", "confirmed"].includes(status)) throw Error("journal_invalid");
      rows[id] = status;
      writeJson(file, rows);
    },
  };
}

module.exports = {journal};
