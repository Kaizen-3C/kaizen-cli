#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Shim: exec the downloaded kaizen binary with the caller's args.
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const binName = process.platform === "win32" ? "kaizen.exe" : "kaizen";
const binPath = path.join(__dirname, binName);

if (!fs.existsSync(binPath)) {
  console.error(
    "kaizen binary not found. Run `npm install -g kaizen-3c-cli` to reinstall, " +
    "or install via pip: pip install kaizen-3c-cli"
  );
  process.exit(1);
}

const result = spawnSync(binPath, process.argv.slice(2), { stdio: "inherit" });

if (result.error) {
  console.error(`Failed to run kaizen: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 0);
