#!/usr/bin/env node
/**
 * verify-fixtures.mjs — validates the generated fixture constants against the
 * canonical JSON sources (hero values that the demo script promises).
 *
 * Run: npm run verify   (also runs inside `npm run check`)
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const DASH = (f) => JSON.parse(readFileSync(resolve(REPO, "data", "fixtures", "dashboard", f), "utf8"));
const DEMO = (f) => JSON.parse(readFileSync(resolve(REPO, "data", "fixtures", "demo", f), "utf8"));
const GEN = readFileSync(resolve(HERE, "..", "src", "data", "fixtures.generated.ts"), "utf8");

const checks = [];
const check = (name, fn) => {
  try {
    checks.push({ name, pass: !!fn() });
  } catch (e) {
    checks.push({ name, pass: false, err: String(e) });
  }
};

// --- hero value contract (docs/01_demo_script.md + VALIDATION_REPORT.md) ---
const alerts = DEMO("alerts.json");
const pv07 = alerts.alerts.find((a) => a.field_id === "PV-07" && a.tier === "critical");
check("PV-07 canopy = 98.2°F", () => pv07 && Math.abs(pv07.canopy_temp_f - 98.2) < 1e-6);
check("PV-07 urgency = 91", () => pv07 && pv07.urgency === 91);
check("PV-07 exceedance = 3.4h", () => pv07 && Math.abs(pv07.exceedance_hours - 3.4) < 1e-6);
check("PV-07 SMS body mentions HARVEST NOW", () => pv07?.sms?.body.includes("HARVEST NOW"));
check("PV-07 SMS body mentions I-16 corridor", () => pv07?.sms?.body.includes("I-16"));

const kpis = DEMO("kpis.json");
const spoilageKpi = kpis.kpis.find((k) => k.id === "spoilage");
check("KPI spoilage ↓23%", () => spoilageKpi?.value === "↓ 23%");
const savingsKpi = kpis.kpis.find((k) => k.id === "savings");
check("KPI savings $180K", () => savingsKpi?.value === "$180K");
check("KPI fuel 12%", () => kpis.kpis.find((k) => k.id === "fuel")?.value === "12%");
check("KPI port 96%", () => kpis.kpis.find((k) => k.id === "port")?.value === "96%");

const corridor = DEMO("corridor.json").response ?? DEMO("corridor.json");
const i16 = corridor.routes.find((r) => r.route_id === "I16");
const i75 = corridor.routes.find((r) => r.route_id === "I75");
check("Corridor recommendation mentions 54%", () => corridor.recommendation.includes("54%"));
check("Corridor recommendation mentions 12% fuel", () => corridor.recommendation.includes("12% fuel"));
check("Corridor recommendation mentions 142 mi", () => corridor.recommendation.includes("142 mi"));
check("I-16 avg 91.3°F", () => i16 && Math.abs(i16.avg_temp_f - 91.3) < 0.6);
check("I-75 avg 97°F band", () => i75 && i75.avg_temp_f >= 96.4 && i75.avg_temp_f <= 97.6);
check("I-16 176 mi", () => i16 && Math.abs(i16.distance_mi - 176) < 2);
check("I-75 318 mi", () => i75 && Math.abs(i75.distance_mi - 318) < 2);

const heat = DASH("heat_frames.json");
check("Heat frames: 10 hours 08:00–17:00", () => Object.keys(heat.frames).length === 10);
check("Heat frames: 720 tiles/hour", () => Object.values(heat.frames).every((f) => f.length === 720));
check("Heat frames: 45 unique fields", () => {
  const ids = new Set();
  for (const feats of Object.values(heat.frames)) for (const ft of feats) ids.add(ft.properties.field_id);
  return ids.size === 45;
});

const fields = DEMO("fields_snapshot.json");
check("45 fields in snapshot", () => fields.length === 45);

// --- captions / timing (data/rehearsal — burned-in + sidecar source) ---
const caps = JSON.parse(readFileSync(resolve(REPO, "data", "rehearsal", "peachstate_coolchain_demo_captions.json"), "utf8"));
check("Captions: 21 blocks", () => caps.length === 21);
check("Captions: all have text + 1–2 lines", () =>
  caps.every((c) => typeof c.text === "string" && c.text.length > 0 && c.lines.length >= 1 && c.lines.length <= 2));
check("Captions: sequential, in-range, non-overlapping", () => {
  let prevEnd = -1;
  for (const c of caps) {
    if (c.start_s < prevEnd - 0.2) return false;
    if (c.end_s > 300 || c.start_s < 0) return false;
    prevEnd = c.end_s;
  }
  return true;
});
const timing = JSON.parse(readFileSync(resolve(REPO, "data", "rehearsal", "peachstate_coolchain_demo_timing.json"), "utf8"));
check("Timing: clicktrack 150 WPM / 0.4s beat", () =>
  timing.master.clicktrack.bpm === 150 && Math.abs(timing.master.clicktrack.beat_s - 0.4) < 1e-9);
check("Timing: 6 scenes span 0→300s", () =>
  timing.scenes.length === 6 && timing.scenes[0].start_s === 0 && timing.scenes[5].end_s === 300);
check("Timing: caption blocks match captions.json", () =>
  JSON.stringify(timing.captions.map((c) => c.text)) === JSON.stringify(caps.map((c) => c.text)));

// --- generated TS actually embeds the numbers ---
check("generated embeds PV-07 98.2", () => GEN.includes("98.2"));
check("generated embeds spoilage −23% KPI", () => GEN.includes("↓ 23%") || GEN.includes("\\u2193 23%"));
check("generated embeds corridor 54% headline", () => GEN.includes("54%"));
check("generated embeds heat hour 08:00", () => GEN.includes("08:00"));
check("generated embeds CAPTIONS", () => GEN.includes("export const CAPTIONS"));
check("generated embeds TIMING + key_beats", () => GEN.includes("export const TIMING") && GEN.includes("key_beats"));

// --- parity: theme mirror matches canonical tokens ---
const tokens = JSON.parse(readFileSync(resolve(REPO, "design", "design_tokens.json"), "utf8"));
const synced = JSON.parse(readFileSync(resolve(HERE, "..", "src", "design", "design_tokens.generated.json"), "utf8"));
check("design_tokens parity (src == canonical)", () => JSON.stringify(tokens) === JSON.stringify(synced));

// --- report ---
const failed = checks.filter((c) => !c.pass);
for (const c of checks) {
  console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.name}${c.err ? ` — ${c.err}` : ""}`);
}
console.log(`\nverify-fixtures: ${checks.length - failed.length}/${checks.length} PASS`);
if (failed.length) process.exit(1);