/**
 * KPI.tsx — Scene 4 (3:30–4:15).
 *
 *  • 4 MetricCards (spoilage ↓23% / savings $180K / fuel 12% / port 96%) with
 *    flip-in entrance, counter rolls, delta chips + sparklines (all from
 *    kpis.json fixtures)
 *  • Secondary metrics row (41 t CO₂e · 45 fields · 1,240 loads · 5 packing houses)
 *  • Heat-intelligence report card (P2: replaces matplotlib dashboard)
 */
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT_BODY, FONT_MONO, RADIUS, SHADOW, TYPE } from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { MetricCard } from "../design/components/MetricCard";
import { LowerThird } from "../design/components/LowerThird";
import { ProgressBar } from "../design/components/ProgressBar";
import { GlobalFonts } from "../design/components/Fonts";
import { easingFromToken } from "../utils/easing";
import { KPI_CARDS, KPI_SECONDARY } from "../data/fixtures";

export const KPI: React.FC = () => {
  const frame = useCurrentFrame();

  const titleIn = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="scene">
        {/* header */}
        <div style={{ position: "absolute", left: 96, top: 72, opacity: titleIn }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.12em" }}>
            Cold Chain Dashboard · July 2025 season
          </div>
          <div style={{ fontFamily: "Space Grotesk, system-ui, sans-serif", fontWeight: 600, fontSize: 40, color: COLORS.cream, marginTop: 6 }}>
            One July season with PeachState CoolChain
          </div>
        </div>

        {/* 4 KPI cards — staggered flip-in at 80ms */}
        <div style={{ position: "absolute", left: 96, top: 220, display: "flex", gap: 20, flexWrap: "wrap", width: 1728 }}>
          {KPI_CARDS.map((card, i) => (
            <MetricCard key={card.id} card={card} from={30 + i * 14} />
          ))}
        </div>

        {/* secondary metrics row */}
        <div style={{ position: "absolute", left: 96, top: 520, display: "flex", gap: 16 }}>
          {KPI_SECONDARY.map((s, i) => {
            const enter = interpolate(frame, [140 + i * 12, 170 + i * 12], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
              easing: easingFromToken("smooth_out"),
            });
            return (
              <div key={s} style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "12px 20px", opacity: enter, transform: `translateY(${(1 - enter) * 16}px)` }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 14, color: COLORS.cream_soft }}>{s}</span>
              </div>
            );
          })}
        </div>

        {/* heat-intelligence report card (P2 artifact slot) */}
        <div style={{ position: "absolute", left: 96, bottom: 120, width: 500 }}>
          <div style={{ background: "rgba(20,29,46,0.92)", border: "1px solid rgba(255,140,66,0.35)", borderRadius: RADIUS.md, padding: 20, boxShadow: SHADOW.glow_peach }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: FONT_BODY, fontSize: 16, color: COLORS.cream, fontWeight: 600 }}>Heat Intelligence Report</div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, marginTop: 3 }}>
                  Fort Valley, GA · 268-page PDF · Premium analytic
                </div>
              </div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 14, color: COLORS.navy, background: COLORS.peach, borderRadius: 999, padding: "10px 22px", fontWeight: 600 }}>
                Download PDF
              </div>
            </div>
          </div>
        </div>

        <LowerThird title="Cold Chain Dashboard" subtitle="every field, every truck, one screen · prove it with one click" accent={COLORS.success} from={20} />
        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};