#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Downloads the platform-appropriate kaizen binary from GitHub Releases,
// verifies it against the SHA-256 published alongside it, and saves it to
// npm/bin/ so the kaizen.js shim can exec it.
//
// Failure policy, split deliberately by cause:
//   network/download failure -> warn, exit 0. `npm install` must not break
//                               because a CDN blipped.
//   checksum unavailable     -> warn, delete the binary, exit 0. An unverified
//                               binary is not installed.
//   checksum MISMATCH        -> delete the binary and FAIL the install. This is
//                               the one case where silence is dangerous.
"use strict";

const https = require("https");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PKG = require("./package.json");
const VERSION = PKG.version;
const REPO = "Kaizen-3C/kaizen-cli";
const BIN_DIR = path.join(__dirname, "bin");

function platformArtifact() {
  const p = process.platform;
  const a = process.arch;

  if (p === "win32" && a === "x64") return `kaizen-windows-x64.exe`;
  if (p === "darwin" && a === "arm64") return `kaizen-macos-arm64`;
  if (p === "linux" && a === "x64") return `kaizen-linux-x64`;

  // Intel macOS is deliberately absent: the macos-13 runner was dropped from
  // the release matrix, so no kaizen-macos-x64 artifact is published. Saying so
  // beats a 404 the caller has to interpret.
  if (p === "darwin" && a === "x64") {
    throw new Error(
      `No prebuilt binary is published for Intel macOS (darwin/x64).\n` +
      `Install via pip instead: pip install kaizen-3c-cli`
    );
  }

  throw new Error(
    `Unsupported platform/arch: ${p}/${a}.\n` +
    `Install via pip instead: pip install kaizen-3c-cli`
  );
}

function httpGet(url, onResponse) {
  return new Promise((resolve, reject) => {
    const request = (u, redirectsLeft) => {
      if (redirectsLeft < 0) {
        reject(new Error("too many redirects"));
        return;
      }
      https
        .get(u, { headers: { "User-Agent": "kaizen-cli-npm-installer" } }, (res) => {
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            res.resume();
            request(res.headers.location, redirectsLeft - 1);
            return;
          }
          if (res.statusCode !== 200) {
            res.resume();
            reject(new Error(`HTTP ${res.statusCode} for ${u}`));
            return;
          }
          onResponse(res, resolve, reject);
        })
        .on("error", reject);
    };
    request(url, 5);
  });
}

function downloadToFile(url, dest) {
  return httpGet(url, (res, resolve, reject) => {
    const file = fs.createWriteStream(dest);
    res.pipe(file);
    file.on("finish", () => file.close(() => resolve()));
    file.on("error", reject);
  });
}

function downloadToString(url) {
  return httpGet(url, (res, resolve, reject) => {
    let body = "";
    res.setEncoding("utf8");
    res.on("data", (chunk) => (body += chunk));
    res.on("end", () => resolve(body));
    res.on("error", reject);
  });
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(file);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
    stream.on("error", reject);
  });
}

// Accepts a bare hex digest or the `<digest>  <filename>` form that sha256sum
// and `shasum -a 256` emit.
function parseDigest(text) {
  const match = String(text).trim().match(/\b([0-9a-fA-F]{64})\b/);
  return match ? match[1].toLowerCase() : null;
}

function removeQuietly(file) {
  try {
    if (fs.existsSync(file)) fs.unlinkSync(file);
  } catch (_) {
    /* best effort */
  }
}

async function main() {
  const artifact = platformArtifact();
  const destName = process.platform === "win32" ? "kaizen.exe" : "kaizen";
  const dest = path.join(BIN_DIR, destName);
  const url = `https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}`;
  const sumUrl = `${url}.sha256`;

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
    await downloadToFile(url, dest);
  } catch (err) {
    removeQuietly(dest);
    // Non-fatal: warn and exit 0 so `npm install` succeeds.
    console.warn(`\nWarning: could not download kaizen binary: ${err.message}`);
    console.warn(`Install via pip instead: pip install kaizen-3c-cli`);
    return;
  }

  let expected = null;
  try {
    expected = parseDigest(await downloadToString(sumUrl));
  } catch (err) {
    console.warn(`\nWarning: could not fetch checksum: ${err.message}`);
  }

  if (!expected) {
    removeQuietly(dest);
    console.warn(
      `\nWarning: no published SHA-256 for ${artifact}; refusing to install an unverified binary.`
    );
    console.warn(`Install via pip instead: pip install kaizen-3c-cli`);
    return;
  }

  const actual = await sha256File(dest);
  if (actual !== expected) {
    removeQuietly(dest);
    console.error(
      `\nCHECKSUM MISMATCH for ${artifact}\n` +
      `  expected: ${expected}\n` +
      `  actual:   ${actual}\n` +
      `The download does not match the checksum published with this release.\n` +
      `It has been deleted and NOT installed. Do not attempt to run it.\n` +
      `Please report this: https://github.com/${REPO}/security/advisories/new`
    );
    process.exitCode = 1;
    return;
  }

  console.log(`  sha256 verified: ${actual}`);

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
