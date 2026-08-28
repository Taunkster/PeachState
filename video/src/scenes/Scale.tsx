/**
 * Scale.tsx — Scene 5 (4:15–5:00).
 *
 *  • Mosaic grid — 3 use cases (Fort Valley orchard / Athens community garden /
 *    Atlanta last-mile) with the same heat signal, same API, 10 mi² Basic plan
 *  • Uses real fixture counts (45 fields) and the PV-07 alert temp
 *  • Closing brand card fades in: tagline + api.fortyguard.com/v1 + QR slot
 */
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT_BODY, FONT_MONO, RADIUS, SHADOW, TYPE } from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { LowerThird } from "../design/components/LowerThird";
import { ProgressBar } from "../design/components/ProgressBar";
import { GlobalFonts } from "../design/components/Fonts";
import { easingFromToken } from "../utils/easing";
import { FIELDS, PV07_ALERT } from "../data/fixtures";

const USE_CASES = [
  {
    title: "Fort Valley orchard",
    sub: `${FIELDS.length} fields · peach + pecan + blueberry + onion`,
    stat: `${Math.round(PV07_ALERT.canopy_temp_f)}°F`,
    statLabel: "canopy right now",
    color: COLORS.peach,
  },
  {
    title: "Athens community garden",
    sub: "UGA trial garden · 1.8 ac · same risk scale",
    stat: "1.8 ac",
    statLabel: "one API call",
    color: COLORS.purple,
  },
  {
    title: "Atlanta last-mile",
    sub: "delivery van · shade-corridor routing · 34°F cooler",
    stat: "34°F",
    statLabel: "cooler in shade corridors",
    color: COLORS.blue,
  },
];

export const Scale: React.FC = () => {
  const frame = useCurrentFrame();

  // mosaic entrance (staggered)
  const mosaicIn = interpolate(frame, [0, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  // brand card fades in for the final ~12s (4:50 hard stop)
  const brandIn = interpolate(frame, [1980, 2100], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_in_out"),
  });

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="scene">
        {/* header */}
        <div style={{ position: "absolute", left: 96, top: 72 }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.12em" }}>
            Scale vision
          </div>
          <div style={{ fontFamily: "Space Grotesk, system-ui, sans-serif", fontWeight: 600, fontSize: 40, color: COLORS.cream, marginTop: 6 }}>
            One temperature signal — field to port to front porch
          </div>
        </div>

        {/* mosaic grid */}
        <div style={{ position: "absolute", left: 96, top: 220, display: "flex", gap: 20, opacity: mosaicIn, transform: `translateY(${(1 - mosaicIn) * 24}px)` }}>
          {USE_CASES.map((c, i) => (
            <div
              key={c.title}
              style={{
                width: 550,
                height: 320,
                background: "rgba(20,29,46,0.85)",
                border: `1px solid ${c.color}44`,
                borderRadius: RADIUS.md,
                padding: 28,
                boxShadow: SHADOW.card,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <div>
                <div style={{ fontFamily: FONT_BODY, fontSize: 22, color: COLORS.cream, fontWeight: 600 }}>{c.title}</div>
                <div style={{ fontFamily: FONT_BODY, fontSize: 14, color: COLORS.slate, marginTop: 6 }}>{c.sub}</div>
              </div>
              <div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 64, color: c.color, fontVariantNumeric: "tabular-nums" }}>{c.stat}</div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.08em" }}>{c.statLabel}</div>
              </div>
              {/* mini risk strip */}
              <div style={{ height: 8, borderRadius: 4, background: "linear-gradient(90deg,#2DD4BF,#A3E635,#FDE047,#FB923C,#EF4444)", opacity: 0.85 }} />
            </div>
          ))}
        </div>

        {/* same-API callout */}
        <div style={{ position: "absolute", left: 96, bottom: 130 }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 16, color: COLORS.cream_soft }}>
            Same FortyGuard API · 10 mi² Basic plan · whole neighborhood protected
          </div>
        </div>

        {/* closing brand card */}
        <div
          style={{
            position: "absolute",
            right: 96,
            bottom: 130,
            background: "rgba(10,15,30,0.92)",
            border: "1px solid rgba(255,140,66,0.4)",
            borderRadius: RADIUS.md,
            padding: "24px 32px",
            boxShadow: SHADOW.glow_peach,
            opacity: brandIn,
            transform: `translateY(${(1 - brandIn) * 30}px)`,
            textAlign: "center",
          }}
        >
          <div style={{ fontFamily: "Space Grotesk, system-ui, sans-serif", fontWeight: 600, fontSize: 26, color: COLORS.cream }}>
            PeachState <span style={{ color: COLORS.peach }}>CoolChain</span>
          </div>
          <div style={{ fontFamily: FONT_MONO, fontSize: 14, color: COLORS.slate, marginTop: 6 }}>api.fortyguard.com/v1</div>
          {/* QR placeholder — replace with real QR in P4 */}
          <div style={{ width: 96, height: 96, margin: "16px auto 0", background: COLORS.cream, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.navy }}>QR</span>
          </div>
        </div>

        <LowerThird title="Scale Vision" subtitle="community gardens + last-mile delivery · protect your corner of Georgia" accent={COLORS.purple} from={10} />
        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};