/**
 * Corridor.tsx — Scene 3 (2:30–3:30), Deck.gl + Vega-Lite.
 *
 *  • Deck.gl PathLayer for I-16 (blue, coastal/cool) and I-75 (red, inland/hot)
 *    with an animated draw (path slices forward ONCE over the scene — no loops)
 *  • ScatterplotLayer truck marker rides the I-16 path (one pass)
 *  • Route chips: I-75 318 mi · 97°F avg  |  I-16 176 mi · 91°F avg
 *  • Fixture-verified headline counters: spoilage −54% · fuel −12%
 *  • Q10 spoilage curves + corridor temp profile as SVG (deterministic).
 *    The canonical declarative version lives in
 *    src/data/vega/corridor-spoilage.vl.json (render via `npm run vega:render`).
 */
import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import DeckGL from "@deck.gl/react";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { COLORS, FONT_BODY, FONT_MONO, RADIUS, SHADOW, TYPE } from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { LowerThird } from "../design/components/LowerThird";
import { ProgressBar } from "../design/components/ProgressBar";
import { CategoricalLegend } from "../design/components/Legend";
import { GlobalFonts } from "../design/components/Fonts";
import { corridorViewState } from "../utils/camera";
import { easingFromToken, ease } from "../utils/easing";
import { rollValue } from "../utils/format";
import { CORRIDOR_I16, CORRIDOR_I75, CORRIDOR_HEADLINE, routeLine, spoilageCurve, RISK_DATA } from "../data/fixtures";
import type { CorridorRoute } from "../data/types";

const DRAW_START = 40;
const DRAW_END = 1600;
const TRUCK_END = 3000;
const CHART_AT = 800; // Moved later to avoid overlap
const LEGEND_AT = 100; // Legend appears earlier
const CHIPS_AT = 200; // Chips appear after legend
const COUNTERS_AT = 1800;
const FUEL_COUNTER_AT = 1950;

export const Corridor: React.FC = () => {
  const frame = useCurrentFrame();

  // Animated route draw: progress 0→1 over DRAW_START..DRAW_END (smooth_in_out)
  const drawP = interpolate(frame, [DRAW_START, DRAW_END], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_in_out"),
  });

  const i16Path = routeLine(CORRIDOR_I16);
  const i75Path = routeLine(CORRIDOR_I75);

  const partial = (path: [number, number][], frac: number): [number, number][] =>
    path.slice(0, Math.max(2, Math.round(path.length * frac)));

  // Truck: one pass along I-16
  const truckP = interpolate(frame, [DRAW_END, 3000], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: (x: number) => ease("smooth_in_out", x),
  });
  const truckPos = pointAlong(i16Path, truckP);

  // Charts entrance - later to avoid overlap
  const chartIn = interpolate(frame, [CHART_AT, CHART_AT + 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  // Legend entrance
  const legendIn = interpolate(frame, [LEGEND_AT, LEGEND_AT + 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  // Chips entrance - staggered after legend
  const chipsIn1 = interpolate(frame, [CHIPS_AT, CHIPS_AT + 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });
  const chipsIn2 = interpolate(frame, [CHIPS_AT + 20, CHIPS_AT + 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });

  // Counters (staggered, gentle roll)
  const spoilage = `${rollValue(frame - COUNTERS_AT, 54, 80)}%`;
  const fuel = `${rollValue(frame - FUEL_COUNTER_AT, 12, 80)}%`;

  const layers = useMemo(() => {
    return [
      new PathLayer({
        id: "i75",
        data: [{ path: partial(i75Path, drawP), color: [248, 113, 113] }],
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: (d: { color: [number, number, number] }) => d.color,
        getWidth: 10,
        widthMinPixels: 3,
        rounded: true,
      }),
      new PathLayer({
        id: "i16",
        data: [{ path: partial(i16Path, drawP), color: [96, 165, 250] }],
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: (d: { color: [number, number, number] }) => d.color,
        getWidth: 10,
        widthMinPixels: 3,
        rounded: true,
      }),
      new ScatterplotLayer({
        id: "truck",
        data: truckPos ? [{ pos: truckPos, color: [255, 140, 66] }] : [],
        getPosition: (d: { pos: [number, number] }) => d.pos,
        getFillColor: (d: { color: [number, number, number] }) => d.color,
        getRadius: 700,
        radiusMinPixels: 9,
        stroked: true,
        getLineColor: [253, 246, 227, 220],
        lineWidthMinPixels: 2,
      }),
    ];
  }, [drawP, truckP]);

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="cool">
        <div style={{ position: "absolute", inset: 0, background: COLORS.charcoal }}>
          <DeckGL viewState={corridorViewState() as any} layers={layers} width="100%" height="100%" controller={false} />
        </div>

        {/* header */}
        <div style={{ position: "absolute", left: 96, top: 72, display: "flex", gap: 12, alignItems: "center", zIndex: 10 }}>
          <div style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "10px 18px", fontFamily: FONT_MONO, fontSize: 16, color: COLORS.cream }}>
            Macon → Port of Savannah
          </div>
          <div style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "10px 18px", fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate }}>
            {CORRIDOR_HEADLINE}
          </div>
        </div>

        {/* route legend - top right, fades in early */}
        <div style={{ position: "absolute", right: 96, top: 72, zIndex: 10, opacity: legendIn, transform: `translateX(${(1 - legendIn) * 20}px)` }}>
          <CategoricalLegend
            title="corridor"
            items={[
              { label: "I-16 coastal · 91°F avg", color: COLORS.blue },
              { label: "I-75 inland · 97°F avg", color: COLORS.red },
              { label: "Reefer #212", color: COLORS.peach },
            ]}
          />
        </div>

        {/* route chips - bottom left, staggered after legend */}
        <div style={{ position: "absolute", left: 96, bottom: 220, display: "flex", flexDirection: "column", gap: 12, zIndex: 10 }}>
          {[
            { route: CORRIDOR_I75, color: COLORS.red },
            { route: CORRIDOR_I16, color: COLORS.blue },
          ].map(({ route, color }, i) => {
            const enter = i === 0 ? chipsIn1 : chipsIn2;
            return (
              <div key={route.route_id} style={{ background: "rgba(20,29,46,0.85)", border: `1px solid ${color}55`, borderRadius: 14, padding: "14px 20px", minWidth: 240, opacity: enter, transform: `translateX(${(1 - enter) * -30}px)` }}>
                <div style={{ fontFamily: FONT_MONO, fontSize: 15, color }}>{route.label}</div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 22, color: COLORS.cream, marginTop: 6 }}>
                  {route.distance_mi} mi · {route.avg_temp_f}°F avg
                </div>
                <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: COLORS.slate, marginTop: 2 }}>
                  peak {route.peak_temp_f}°F · {route.eta_hours}h ETA
                </div>
              </div>
            );
          })}
          {/* headline counters - stacked vertically, spaced from chips */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
            <div style={{ background: "rgba(20,29,46,0.92)", border: `1px solid ${COLORS.success}55`, borderRadius: 14, padding: "12px 18px", minWidth: 240 }}>
              <div style={{ fontFamily: FONT_MONO, fontSize: 28, color: COLORS.success }}>−{spoilage}</div>
              <div style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate }}>spoilage risk this load</div>
            </div>
            <div style={{ background: "rgba(20,29,46,0.92)", border: `1px solid ${COLORS.info}55`, borderRadius: 14, padding: "12px 18px", minWidth: 240 }}>
              <div style={{ fontFamily: FONT_MONO, fontSize: 28, color: COLORS.info }}>−{fuel}</div>
              <div style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate }}>fuel per trip</div>
            </div>
          </div>
        </div>

        {/* charts row (Q10 spoilage + temp profile) — positioned above chips, below map */}
        <div style={{ position: "absolute", left: 96, right: 96, bottom: 400, display: "flex", gap: 16, opacity: chartIn, transform: `translateY(${(1 - chartIn) * 20}px)`, zIndex: 5 }}>
          <CorridorTempProfile />
          <SpoilageChart />
        </div>

        <LowerThird title="Cool Corridor Routing" subtitle="heat-exposure routing, not miles · Q10 spoilage kinetics" accent={COLORS.info} from={10} />
        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};

/** Point along a [lon,lat] polyline at fraction t. */
function pointAlong(path: [number, number][], t: number): [number, number] | null {
  if (!path.length) return null;
  if (t <= 0) return path[0];
  if (t >= 1) return path[path.length - 1];
  const target = t * (path.length - 1);
  const i = Math.floor(target);
  const frac = target - i;
  const a = path[i];
  const b = path[Math.min(i + 1, path.length - 1)];
  return [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac];
}

/** Corridor temp profile (I-16 vs I-75) — SVG mirror of a Vega-Lite line spec. */
const CorridorTempProfile: React.FC = () => {
  const W = 560;
  const H = 190;
  const PAD = { l: 44, r: 12, t: 18, b: 30 };
  const maxMi = Math.max(CORRIDOR_I16.distance_mi, CORRIDOR_I75.distance_mi);
  const maxT = Math.max(CORRIDOR_I16.peak_temp_f, CORRIDOR_I75.peak_temp_f) + 1;
  const minT = Math.min(CORRIDOR_I16.avg_temp_f, CORRIDOR_I75.avg_temp_f) - 4;

  const x = (mi: number) => PAD.l + (mi / maxMi) * (W - PAD.l - PAD.r);
  const y = (t: number) => PAD.t + (1 - (t - minT) / (maxT - minT)) * (H - PAD.t - PAD.b);

  const line = (route: CorridorRoute) =>
    route.points.map((p) => `${x(p.d_mi).toFixed(1)},${y(p.temp_f).toFixed(1)}`).join(" ");

  const gridY = [minT + 0, minT + 2, minT + 4, minT + 6, minT + 8, minT + 10].filter((v) => v <= maxT);

  return (
    <ChartCard title="corridor temp profile · °F along route">
      <svg width={560} height={H}>
        {gridY.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="rgba(253,246,227,0.06)" />
            <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end" fill={COLORS.slate_dim} fontSize={11} fontFamily="JetBrains Mono, monospace">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {[0, 40, 80, 120, 160].filter((m) => m <= maxMi).map((m) => (
          <text key={m} x={x(m)} y={H - 8} textAnchor="middle" fill={COLORS.slate_dim} fontSize={11} fontFamily="JetBrains Mono, monospace">
            {m}mi
          </text>
        ))}
        <polyline points={line(CORRIDOR_I75)} fill="none" stroke={COLORS.red} strokeWidth={3} opacity={0.9} />
        <polyline points={line(CORRIDOR_I16)} fill="none" stroke={COLORS.blue} strokeWidth={3.5} opacity={0.95} />
      </svg>
    </ChartCard>
  );

  };

/** Q10 spoilage degree-hours curves (4 crops) — SVG mirror of corridor-spoilage.vl.json. */
const SpoilageChart: React.FC = () => {
  const W = 560;
  const H = 190;
  const PAD = { l: 44, r: 12, t: 18, b: 30 };

  const curves = RISK_DATA.spoilage;
  const maxH = Math.max(...curves.map((c) => c.curve[c.curve.length - 1]?.h ?? 0));
  const maxDh = Math.max(...curves.map((c) => Math.max(...c.curve.map((p) => p.dh))));
  const maxTol = Math.max(...curves.map((c) => c.tolerance_deg_hours));
  const yMax = Math.max(maxDh, maxTol) * 1.15;

  const x = (h: number) => PAD.l + (h / maxH) * (W - PAD.l - PAD.r);
  const y = (dh: number) => PAD.t + (1 - dh / yMax) * (H - PAD.t - PAD.b);

  const CROP_COLOR: Record<string, string> = {
    blueberry: COLORS.purple,
    peach: COLORS.orange,
    onion: COLORS.yellow,
    pecan: COLORS.sky,
  };

  const gridY = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);

  return (
    <ChartCard title="Q10 spoilage kinetics · degree-hours">
      <svg width={W} height={H}>
        {gridY.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="rgba(253,246,227,0.06)" />
            <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end" fill={COLORS.slate_dim} fontSize={11} fontFamily="JetBrains Mono, monospace">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {[0, 4, 8, 12].filter((h) => h <= maxH).map((h) => (
          <text key={h} x={x(h)} y={H - 8} textAnchor="middle" fill={COLORS.slate_dim} fontSize={11} fontFamily="JetBrains Mono, monospace">
            {h}h
          </text>
        ))}
        {/* tolerance lines */}
        {curves.map((c) => (
          <g key={`tol-${c.crop}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(c.tolerance_deg_hours)} y2={y(c.tolerance_deg_hours)} stroke={CROP_COLOR[c.crop] ?? COLORS.slate} strokeDasharray="4 5" strokeWidth={1.4} opacity={0.55} />
            <polyline
              points={c.curve.map((p) => `${x(p.h).toFixed(1)},${y(p.dh).toFixed(1)}`).join(" ")}
              fill="none"
              stroke={CROP_COLOR[c.crop] ?? COLORS.slate}
              strokeWidth={2.6}
            />
          </g>
        ))}
        {/* legend */}
        {curves.map((c, i) => (
          <g key={`lg-${c.crop}`}>
            <rect x={PAD.l + i * 118} y={PAD.t - 14} width={10} height={10} rx={2} fill={CROP_COLOR[c.crop] ?? COLORS.slate} />
            <text x={PAD.l + i * 118 + 14} y={PAD.t - 5} fill={COLORS.slate} fontSize={11} fontFamily="JetBrains Mono, monospace">
              {c.crop}
            </text>
          </g>
        ))}
      </svg>
    </ChartCard>
  );

  };

const ChartCard: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{ background: "rgba(20,29,46,0.9)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: RADIUS.sm, padding: "14px 16px", boxShadow: SHADOW.card, flex: 1 }}>
    <div style={{ fontFamily: FONT_MONO, fontSize: 12, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 6 }}>
      {title}
    </div>
    {children}
  </div>
);