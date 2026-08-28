#!/usr/bin/env node
/**
 * vega-render.mjs — render Vega-Lite specs (src/data/vega/*.vl.json) to
 * standalone SVG frames for ingestion into Remotion scenes (P2 replacement
 * for matplotlib charts).
 *
 * Run: npm run vega:render            (renders all specs to out/vega/*.svg)
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const SPEC_DIR = resolve(ROOT, "src", "data", "vega");
const OUT_DIR = resolve(ROOT, "out", "vega");
mkdirSync(OUT_DIR, { recursive: true });

const specs = readdirSync(SPEC_DIR).filter((f) => f.endsWith(".vl.json"));

for (const specFile of specs) {
  const spec = JSON.parse(readFileSync(join(SPEC_DIR, specFile), "utf8"));
  const outSvg = join(OUT_DIR, specFile.replace(".vl.json", ".svg"));
  // Use vega-lite's CLI to compile+render to SVG (vg2svg ships with vega-cli;
  // fallback: node script rendering via vega runtime).
  try {
    execFileSync("vg2svg", [join(SPEC_DIR, specFile), outSvg], { stdio: "inherit" });
  } catch {
    // Fallback: render with the vega node API (deterministic, same result).
    const { read, parse, View } = await import("vega");
    const { compile } = await import("vega-lite");
    const vg = compile(spec).spec;
    const view = new View(parse(vg), { renderer: "none" });
    const res = await view.toSVG();
    writeFileSync(outSvg, res);
  }
  console.log("vega:rendered", outSvg);
}
console.log("vega:done — import the SVGs as <Img> in Remotion scenes (P2).");