#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Downloads the platform-appropriate kaizen binary from GitHub Releases and
// saves it to npm/bin/ so the kaizen.js shim can exec it.
"use strict";

const https = require("https");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const PKG = require("./package.json");
const VERSION = PKG.version;
const REPO = "Kaizen-3C/kaizen-cli";
const BIN_DIR = path.join(__dirname, "bin");

function platformArtifact() {
  const p = process.platform;
  const a = process.arch;

  if (p === "win32" && a === "x64") return `kaizen-windows-x64.exe`;
  if (p === "darwin" && a === "x64") return `kaizen-macos-x64`;
  if (p === "darwin" && a === "arm64") return `kaizen-macos-arm64`;
  if (p === "linux" && a === "x64") return `kaizen-linux-x64`;

  throw new Error(
    `Unsupported platform/arch: ${p}/${a}.\n` +
    `Install via pip instead: pip install kaizen-3c-cli`
  );
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const request = (u) => {
      https.get(u, { headers: { "User-Agent": "kaizen-cli-npm-installer" } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          request(res.headers.location);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode} for ${u}`));
          return;
        }
        res.pipe(file);
        file.on("finish", () => file.close(resolve));
      }).on("error", reject);
    };
    request(url);
  });
}

async function main() {
  const artifact = platformArtifact();
  const destName = process.platform === "win32" ? "kaizen.exe" : "kaizen";
  const dest = path.join(BIN_DIR, destName);
  const url = `https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}`;

  if (!fs.existsSync(BIN_DIR)) fs.mkdirSync(BIN_DIR, { recursive: true });

  // Skip if already present and correct version
  const markerFile = path.join(BIN_DIR, ".installed-version");
  if (
    fs.existsSync(dest) &&
    fs.existsSync(markerFile) &&
    fs.readFileSync(markerFile, "utf8").trim() === VERSION
  ) {
    console.log(`kaizen ${VERSION} already installed.`);
    return;
  }

  console.log(`Downloading kaizen ${VERSION} for ${process.platform}/${process.arch} ...`);
  console.log(`  from: ${url}`);

  try {
    await download(url, dest);
  } catch (err) {
    // Clean up partial download
    if (fs.existsSync(dest)) fs.unlinkSync(dest);
    // Non-fatal: warn and exit 0 so `npm install` succeeds.
    // The shim will attempt download again on first `kaizen` invocation.
    console.warn(`\nWarning: could not download kaizen binary: ${err.message}`);
    console.warn(`The binary will be fetched on first use, or install via pip: pip install kaizen-3c-cli`);
    return;
  }

  // Make executable on Unix
  if (process.platform !== "win32") {
    fs.chmodSync(dest, 0o755);
  }

  fs.writeFileSync(markerFile, VERSION);
  console.log(`kaizen ${VERSION} installed.`);
}

main().catch((err) => {
  // Non-fatal: unsupported platform or unexpected error — warn, don't block install.
  console.warn(`Warning: kaizen postinstall skipped: ${err.message}`);
  console.warn(`Install via pip instead: pip install kaizen-3c-cli`);
});
