/**
 * HarvestAlert.tsx — Scene 2 (1:30–2:30).
 *
 *  • Alert banner slides in from the right (snap-in), single red edge pulse at
 *    alert-instant (one shot — motion encodes state, no perpetual loops)
 *  • PV-07 alert card with fixture metrics
 *  • SMS phone mockup types the fixture SMS body (40ms/char token)
 *  • Status toasts stack once (SMS SENT · FOREMAN CONFIRMED · PACKING HOUSE NOTIFIED)
 */
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT_BODY, FONT_MONO, RADIUS, SHADOW, TYPE } from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { SmsPhone } from "../design/components/SmsPhone";
import { LowerThird } from "../design/components/LowerThird";
import { ProgressBar } from "../design/components/ProgressBar";
import { GlobalFonts } from "../design/components/Fonts";
import { easingFromToken } from "../utils/easing";
import { PV07_ALERT, ACTIVE_ALERTS, criticalFields, FIELDS_BY_ID } from "../data/fixtures";
import { tierColor } from "../data/colors";

const BANNER_AT = 30;
const CARD_AT = 150;
const SMS_AT = 320;

export const HarvestAlert: React.FC = () => {
  const frame = useCurrentFrame();
  const a = PV07_ALERT;

  // Banner: slide in from right with snap easing
  const bannerIn = interpolate(frame, [BANNER_AT, BANNER_AT + 24], [620, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("snap"),
  });
  // Single edge pulse at alert-instant (one shot over 40 frames)
  const pulse = interpolate(frame, [BANNER_AT, BANNER_AT + 40], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_in_out"),
  });

  const cardIn = interpolate(frame, [CARD_AT, CARD_AT + 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  const other = ACTIVE_ALERTS.filter((al) => al.field_id !== a.field_id);
  const crit = criticalFields();

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="alert">
        {/* red glow + one-shot pulse */}
        <div
          style={{
            position: "absolute",
            right: 0,
            top: 0,
            bottom: 0,
            width: "45%",
            background: "radial-gradient(circle at right center, rgba(239,68,68,0.16), transparent 70%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            boxShadow: `inset 0 0 ${120 * pulse}px rgba(239,68,68,${0.25 * pulse})`,
            opacity: pulse,
          }}
        />

        {/* alert banner */}
        <div
          style={{
            position: "absolute",
            top: 72,
            left: 96,
            right: 96,
            display: "flex",
            alignItems: "center",
            gap: 16,
            background: "rgba(20,29,46,0.92)",
            border: "1px solid rgba(239,68,68,0.5)",
            borderRadius: RADIUS.md,
            padding: "18px 24px",
            boxShadow: SHADOW.glow_danger,
            transform: `translateX(${bannerIn}px)`,
          }}
        >
          <div style={{ fontSize: 28, color: COLORS.danger, fontWeight: 700 }}>⚠</div>
          <div style={{ flex: 1 }}>
            <span style={{ fontFamily: FONT_MONO, fontSize: 22, color: COLORS.danger, fontWeight: 600 }}>
              FIELD {a.field_id} CRITICAL
            </span>
            <span style={{ fontFamily: FONT_BODY, fontSize: 18, color: COLORS.cream_soft, marginLeft: 12 }}>
              canopy risk {a.urgency}/100 · {a.canopy_temp_f}°F · +{Math.round(a.exceedance_hours)}h exceedance forecast
            </span>
          </div>
          <div style={{ fontFamily: FONT_MONO, fontSize: 18, color: COLORS.navy, background: COLORS.danger, borderRadius: 999, padding: "8px 20px", fontWeight: 600 }}>
            {a.recommended_action.replace("_", " ")}
          </div>
        </div>

        {/* left column: alert list + critical fields */}
        <div style={{ position: "absolute", left: 96, top: 220, width: 560, opacity: cardIn }}>
          <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 12 }}>
            Active alerts · {ACTIVE_ALERTS.length}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {other.slice(0, 3).map((al) => {
              const f = FIELDS_BY_ID[al.field_id];
              return (
                <div key={al.field_id} style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <span style={{ fontFamily: FONT_MONO, fontSize: 15, color: COLORS.cream }}>{al.field_id}</span>
                    <span style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate, marginLeft: 8 }}>{f?.name}</span>
                  </div>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: tierColor(al.tier) }}>
                    {al.canopy_temp_f}°F · {al.urgency}/100
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 24 }}>
            <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 10 }}>
              Agent watch · {crit.length} fields ≥ 80 urgency
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {crit.map((c) => (
                <div key={c.field_id} style={{ background: "rgba(10,15,30,0.6)", border: `1px solid ${tierColor(c.tier)}44`, borderRadius: 999, padding: "5px 14px", fontFamily: FONT_MONO, fontSize: 13, color: COLORS.cream_soft }}>
                  {c.field_id} · {c.urgency}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* right column: SMS phone mockup */}
        <div style={{ position: "absolute", right: 96, top: 220 }}>
          <SmsPhone sms={a.sms!} from={SMS_AT} width={400} />
          {/* packing house card */}
          <div style={{ marginTop: 16, background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "14px 18px" }}>
            <div style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate }}>{a.packing_house.name}</div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 14, color: COLORS.cream_soft, marginTop: 4 }}>
              {a.packing_house.truck_id} · precool {new Date(a.packing_house.precool_slot).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}
            </div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 14, color: COLORS.slate, marginTop: 2 }}>{a.packing_house.inbound_quantity} inbound</div>
          </div>
        </div>

        <LowerThird title="Harvest Alert → Auto-SMS" subtitle={`${a.field_id} harvest now · agent next check in 15 min`} accent={COLORS.danger} from={20} />
        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};