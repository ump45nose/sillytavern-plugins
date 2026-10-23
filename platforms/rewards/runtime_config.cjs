"use strict";
const path = require("node:path");
const common = require("./browser_common.cjs");
const interaction = require("./interaction.cjs");
const {writeJson} = require("../../common/atomic_json.cjs");

function readConfig(stateDir) {
  try { return common.boundedJson(path.join(stateDir, "native-config.json"), 65536); }
  catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
}

function browserOptions(stateDir, config, proxy, device = "desktop", onState = () => {}, pacing) {
  return {
    proxy,
    region: config.region,
    contextOptions: config[device],
    timezoneOffset: config.timezoneOffset,
    pacing: pacing || interaction.create(config.interaction),
    onVerifiedState(value) {
      writeJson(path.join(stateDir, device === "mobile" ? "storage-state.mobile.json" : "storage-state.json"),
        value, 1024 * 1024);
      onState(value);
    },
  };
}

module.exports = {readConfig, browserOptions};
