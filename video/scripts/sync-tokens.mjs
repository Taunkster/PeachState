#!/usr/bin/env node
/**
 * sync-tokens.mjs — copies the canonical design_tokens.json into
 * video/src/design/design_tokens.generated.json so the Remotion project is
 * self-contained while design/design_tokens.json stays the single source of truth.
 *
 * Run: npm run tokens:sync
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, ".."); // video/
const SRC = resolve(ROOT, "..", "design", "design_tokens.json");
const DST = resolve(ROOT, "src", "design", "design_tokens.generated.json");

if (!SRC) {
  console.error("design_tokens.json not found:", SRC);
  process.exit(1);
}

const raw = readFileSync(SRC, "utf8");
JSON.parse(raw); // fail loudly if invalid
mkdirSync(dirname(DST), { recursive: true });
writeFileSync(DST, raw);

const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex").slice(0, 16);
console.log(`tokens:synced ${SRC}`);
console.log(`  -> ${DST}`);
console.log(`  sha256(src)=${sha(SRC)} sha256(dst)=${sha(DST)}`);
