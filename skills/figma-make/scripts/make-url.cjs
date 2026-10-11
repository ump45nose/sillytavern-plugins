#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const LZString = require("./vendor/lz-string.cjs");

function makeUrl(prompt) {
  if (typeof prompt !== "string" || !prompt.trim()) {
    throw new Error("Provide a non-empty text prompt on stdin.");
  }
  if (prompt.length > 50000) {
    throw new Error("Prompt exceeds 50,000 UTF-16 code units.");
  }
  const encoded = LZString.compressToEncodedURIComponent(prompt);
  if (LZString.decompressFromEncodedURIComponent(encoded) !== prompt) {
    throw new Error("Prompt compression failed round-trip verification.");
  }
  return `https://www.figma.com/make/new#prompt=${encoded}`;
}

if (require.main === module) {
  try {
    if (process.argv.length !== 2) {
      throw new Error("Usage: node make-url.cjs < prompt.txt");
    }
    process.stdout.write(makeUrl(fs.readFileSync(0, "utf8")) + "\n");
  } catch (error) {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  }
}

module.exports = { makeUrl };
