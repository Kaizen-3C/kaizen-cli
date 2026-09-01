#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copies LICENSE and NOTICE from the repository root into this package
// directory so they ship inside the published tarball.
//
// Apache-2.0 §4(a) requires recipients of a distribution to receive a copy of
// the License, and §4(d) requires the NOTICE attributions to travel with it.
// npm only auto-includes LICENSE/NOTICE found in the *package* directory, and
// this package lives in npm/, not the repo root -- so without this step the
// published tarball declares "license": "Apache-2.0" and ships neither file.
//
// Copying at pack time rather than committing duplicates keeps the root files
// the single source of truth; the copies are gitignored.
"use strict";

const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const ROOT = path.join(HERE, "..");
const FILES = ["LICENSE", "NOTICE"];

let failed = false;

for (const name of FILES) {
  const src = path.join(ROOT, name);
  const dest = path.join(HERE, name);

  if (!fs.existsSync(src)) {
    console.error(`prepack: missing ${src} -- cannot ship a package without it.`);
    failed = true;
    continue;
  }

  fs.copyFileSync(src, dest);
  console.log(`prepack: copied ${name} (${fs.statSync(dest).size} bytes)`);
}

if (failed) {
  // Fail the pack rather than publish an Apache-2.0 package with no licence text.
  process.exit(1);
}
