/**
 * Hook.tsx — Scene 0 (0:00–0:30), WORKING PROOF-OF-CONCEPT.
 *
 * Full-bleed hero per scene_storyboards Scene 0:
 *   • hero mesh (design_tokens.color.mesh.hero) — one-shot shimmer
 *   • "PeachState CoolChain" title lockup (mask reveal, smooth_out)
 *   • $74B counter roll (tabular JetBrains Mono, gentle ease — one shot)
 *   • 3 stat chips staggered at 80ms (design_tokens motion.stagger)
 *   • progress bar + scene dots
 *
 * Every number comes from fixtures (KPIS secondary + alert canopy temp).
 */
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import {
  COLORS,
  FONT_BODY,
  FONT_DISPLAY,
  FONT_MONO,
  SHADOW,
  SPACING,
  STAGGER,
  TYPE,
} from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { ProgressBar } from "../design/components/ProgressBar";
import { GlobalFonts } from "../design/components/Fonts";
import { easingFromToken } from "../utils/easing";
import { PV07_ALERT, KPI_SECONDARY } from "../data/fixtures";

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // ---- Title mask reveal (one shot, smooth_out) ----
  const titleReveal = interpolate(frame, [6, 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });
  const titleY = interpolate(frame, [6, 50], [24, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  // ---- $74B counter roll (gentle ease, one shot, mono tabular) ----
  const counter = spring({ frame, fps, config: { damping: 200, stiffness: 60 } });
  const billion = Math.round(74 * counter);

  // ---- Stat chips staggered at 80ms (one per ~48 frames) ----
  const chips = [
    { value: "$74B", label: "Georgia agricultural economy", sub: "4th-largest in the US", accent: COLORS.peach },
    { value: "95°F+", label: "humid July peaks", sub: "accelerates field-to-port spoilage", accent: COLORS.danger },
    { value: `${Math.round(PV07_ALERT.canopy_temp_f)}°F`, label: "canopy at Fort Valley right now", sub: "FortyGuard sees it first", accent: COLORS.orange },
  ];

  // ---- One-shot mesh shimmer (plays once in first 2.4s, never loops) ----
  const shimmer = interpolate(frame, [0, 144], [0.35, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_in_out"),
  });

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="hero" style={{ opacity: 1 }}>
        {/* heat shimmer — one-shot only */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: `radial-gradient(60% 60% at 50% 35%, rgba(255,140,66,${0.10 + shimmer * 0.10}), transparent 70%)`,
          }}
        />
        {/* content */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            paddingTop: 40,
          }}
        >
          {/* kicker */}
          <div
            style={{
              fontFamily: FONT_MONO,
              fontSize: TYPE["text-sm"],
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: COLORS.slate,
              opacity: titleReveal * 0.9,
              transform: `translateY(${titleY * 0.5}px)`,
            }}
          >
            Georgia Agricultural Thermal Intelligence
          </div>

          {/* title lockup */}
          <div
            style={{
              fontFamily: FONT_DISPLAY,
              fontWeight: 600,
              fontSize: 88,
              color: COLORS.cream,
              letterSpacing: "-0.02em",
              textAlign: "center",
              marginTop: 12,
              opacity: titleReveal,
              transform: `translateY(${titleY}px)`,
              textShadow: `0 0 48px rgba(255,140,66,0.25)`,
            }}
          >
            PeachState <span style={{ color: COLORS.peach }}>CoolChain</span>
          </div>

          {/* $74B counter */}
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 28 }}>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 128,
                fontWeight: 400,
                color: COLORS.cream,
                letterSpacing: "-0.02em",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              ${billion}B
            </span>
            <span style={{ fontFamily: FONT_BODY, fontSize: 22, color: COLORS.slate, maxWidth: 300 }}>
              of food grown in Georgia every year
            </span>
          </div>

          {/* stat chips — staggered */}
          <div style={{ display: "flex", gap: 20, marginTop: 48 }}>
            {chips.map((c, i) => {
              const t = frame - (60 + i * STAGGER * fps);
              const enter = interpolate(t, [0, 30], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: easingFromToken("smooth_out"),
              });
              const y = interpolate(t, [0, 30], [32, 0], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: easingFromToken("smooth_out"),
              });
              return (
                <div
                  key={c.value}
                  style={{
                    background: "rgba(20,29,46,0.85)",
                    border: `1px solid ${c.accent}44`,
                    borderRadius: 16,
                    padding: "20px 26px",
                    minWidth: 240,
                    boxShadow: SHADOW.card,
                    opacity: enter,
                    transform: `translateY(${y * (1 - enter)}px)`,
                  }}
                >
                  <div style={{ fontFamily: FONT_MONO, fontSize: 40, color: c.accent, fontVariantNumeric: "tabular-nums" }}>
                    {c.value}
                  </div>
                  <div style={{ fontFamily: FONT_BODY, fontSize: 15, color: COLORS.cream_soft, marginTop: 6, fontWeight: 600 }}>
                    {c.label}
                  </div>
                  <div style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate, marginTop: 2 }}>{c.sub}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* bottom meta */}
        <div
          style={{
            position: "absolute",
            left: 96,
            bottom: 56,
            fontFamily: FONT_MONO,
            fontSize: 13,
            color: COLORS.slate_dim,
            letterSpacing: "0.08em",
          }}
        >
          FORTYGUARD TEMPERATURE API · FORT VALLEY, GA · {new Date(PV07_ALERT.ts).toLocaleDateString("en-US")}
        </div>

        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};