/**
 * FieldMap.tsx — Scene 1 (0:30–1:30), single-canvas Deck.gl with OSM base layer.
 *
 * The heatmap fix (2026-08-28):
 *   • OSM raster base map rendered INSIDE DeckGL via TileLayer+BitmapLayer —
 *     ONE WebGL canvas, ONE camera, so the heatmap/polygons are structurally
 *     aligned with the base map at every frame (previous MapLibre overlay
 *     painted its opaque canvas ON TOP of DeckGL → heatmap was invisible, and
 *     its static camera diverged from the animated flyTo viewState).
 *   • TileLayer default updateStrategy "no-overlap" keeps coarse tiles while
 *     zooming in → no grey gaps while fine tiles load.
 *   • HeatmapLayer = GPU kernel-density surface fed by real fixture tile
 *     centroids (data/fixtures dashboard/heat_frames.json → HEAT_POINTS_BY_HOUR)
 *   • colorRange = design_tokens heat.ramp_smooth_24 (24-stop, 80–105°F)
 *   • GeoJsonLayer overlays the 45 field polygons (tier fill, low opacity)
 *   • Camera: one purposeful flyTo (GA → Fort Valley, smooth_out), then a
 *     single time-scrub forward 08:00→15:00 (never wraps, never loops)
 *   • Real heat legend with °F ticks (not a 4-tier box)
 */
import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import DeckGL from "@deck.gl/react";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { GeoJsonLayer, BitmapLayer } from "@deck.gl/layers";
import { TileLayer } from "@deck.gl/geo-layers";
import { COLORS, FONT_BODY, FONT_MONO } from "../design/theme";
import { MeshBackground } from "../design/components/MeshBackground";
import { HeatLegend, CategoricalLegend } from "../design/components/Legend";
import { ProgressBar } from "../design/components/ProgressBar";
import { LowerThird } from "../design/components/LowerThird";
import { GlobalFonts } from "../design/components/Fonts";
import { flyTo, VIEW_GA, VIEW_FORT_VALLEY } from "../utils/camera";
import { easingFromToken } from "../utils/easing";
import { heatColorRange, tierColor, tierOpacity } from "../data/colors";
import { HOURS, HEAT_POINTS_BY_HOUR, fieldGeoJson, FIELDS_BY_ID } from "../data/fixtures";
import { clockLabel } from "../utils/format";
import type { RiskTier } from "../data/types";

const SCRUB_START = 60;      // frames: flyTo completes
const SCRUB_END = 3000;      // frames: hours 08:00→15:00 scrubbed
const PANEL_AT = 3050;       // frames: PV-07 side panel slides in

/**
 * OSM raster base layer rendered INSIDE DeckGL (single canvas, single camera).
 * Default updateStrategy "no-overlap" keeps coarse tiles while zooming, so the
 * base map never shows grey gaps while fine tiles load. Attribution per OSM
 * policy is drawn in the scene JSX below the header chips.
 */
const OSM_BASE_LAYER = new TileLayer({
  id: "osm-base",
  data: [
    "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
  ],
  tileSize: 256,
  minZoom: 0,
  maxZoom: 19,
  // "overlap": keep coarse tiles visible until fine tiles arrive while the
  // camera zooms in — no dark/grey gaps mid-flight. "no-overlap" (default)
  // discards overlapping coarse tiles immediately → visible gaps.
  updateStrategy: "overlap",
  tileCacheMaxSize: 50,
  renderSubLayers: (props) => {
    const { boundingBox } = props.tile;
    return new BitmapLayer(props, {
      data: undefined,
      image: props.data,
      bounds: [
        boundingBox[0][0],
        boundingBox[0][1],
        boundingBox[1][0],
        boundingBox[1][1],
      ],
    });
  },
});

export const FieldMap: React.FC = () => {
  const frame = useCurrentFrame();

  // ---- Camera: one flyTo (GA overview → Fort Valley), no zoompan ----
  const viewState = flyTo(frame, VIEW_GA, VIEW_FORT_VALLEY, SCRUB_START);

  // ---- Time: single forward scrub 08:00→15:00 (index 0→7), then hold ----
  const scrubP = interpolate(frame, [SCRUB_START, 3000], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_in_out"),
  });
  const hourIndex = Math.min(HOURS.length - 1, Math.round(scrubP * 7)); // cap at 15:00
  const hour = HOURS[hourIndex];

  const points = useMemo(() => HEAT_POINTS_BY_HOUR[hour] ?? [], [hour]);

  // tier per field at this hour (for polygon fill overlay)
  const tierByField: Record<string, RiskTier> = useMemo(() => {
    const out: Record<string, RiskTier> = {};
    for (const p of points) out[p.fieldId] = p.tier;
    return out;
  }, [points]);

  const geojson = useMemo(() => fieldGeoJson(tierByField), [tierByField]);

  // PV-07 side panel reveal
  const PANEL_AT = 3050;
  const panelP = interpolate(frame, [PANEL_AT, PANEL_AT + 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: easingFromToken("smooth_out"),
  });
  const pv = FIELDS_BY_ID["PV-07"];

  const layers = useMemo(() => {
    return [
      OSM_BASE_LAYER,
      new HeatmapLayer({
        id: `heat-${hour}`,
        data: points,
        getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
        getWeight: (d: { tcmF: number }) => d.tcmF,
        colorRange: heatColorRange(),
        radiusPixels: 42,
        intensity: 1.4,
        threshold: 0.02,
        aggregation: "SUM",
        debounceTimeOut: 0,
      }),
      new GeoJsonLayer({
        id: "fields",
        data: geojson,
        stroked: true,
        filled: true,
        lineWidthMinPixels: 1.5,
        getLineColor: [253, 246, 227, 90],
        getFillColor: (f: { properties?: { tier?: RiskTier } }) => {
          const tier = f.properties?.tier ?? "low";
          const [r, g, b] = hexToRgbArr(tierColor(tier));
          return [r, g, b, Math.round(255 * tierOpacity(tier))];
        },
        pickable: true,
      }),
    ];
  }, [points, geojson, hour]);

  return (
    <AbsoluteFill>
      <GlobalFonts />
      <MeshBackground kind="scene">
        {/* DeckGL canvas: OSM base layer + heatmap + field polygons (single canvas) */}
        <div style={{ position: "absolute", inset: 0, background: COLORS.charcoal }}>
          <DeckGL
            viewState={viewState as any}
            layers={layers}
            width="100%"
            height="100%"
            controller={false}
            onViewStateChange={() => {}}
          />
          {/* OSM attribution (policy) — top-left, below the header chips */}
          <div
            style={{
              position: "absolute",
              left: 96,
              top: 148,
              fontFamily: FONT_MONO,
              fontSize: 11,
              color: COLORS.slate_dim,
              background: "rgba(20,29,46,0.6)",
              padding: "2px 8px",
              borderRadius: 6,
              zIndex: 2,
            }}
          >
            © OpenStreetMap contributors
          </div>
        </div>

        {/* header chips */}
        <div style={{ position: "absolute", left: 96, top: 72, display: "flex", gap: 12, alignItems: "center", zIndex: 10 }}>
          <div style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "10px 18px" }}>
            <div style={{ fontFamily: FONT_MONO, fontSize: 24, color: COLORS.cream, fontVariantNumeric: "tabular-nums" }}>
              {clockLabel(hour)}
            </div>
          </div>
          <div style={{ background: "rgba(20,29,46,0.85)", border: "1px solid rgba(253,246,227,0.08)", borderRadius: 12, padding: "10px 18px", fontFamily: FONT_BODY, fontSize: 14, color: COLORS.cream_soft }}>
            Fort Valley + Albany · 45 fields
          </div>
        </div>

        {/* live heat legend (24-stop, °F ticks) */}
        <HeatLegend title="canopy °F · tcm" />

        {/* route/tier legend */}
        <CategoricalLegend
          title="risk tier"
          items={[
            { label: "LOW", color: COLORS.success },
            { label: "MEDIUM", color: COLORS.warning },
            { label: "HIGH", color: COLORS.high },
            { label: "CRITICAL", color: COLORS.danger },
          ]}
        />

        {/* PV-07 side panel (payoff) */}
        {frame > 3050 && pv ? (
          <div
            style={{
              position: "absolute",
              right: 96,
              bottom: 96,
              width: 360,
              background: "rgba(20,29,46,0.92)",
              border: `1px solid ${tierColor(pv.risk.tier)}55`,
              borderRadius: 16,
              padding: 24,
              boxShadow: "0 24px 64px rgba(0,0,0,0.45)",
              transform: `translateX(${(1 - interpolate(frame, [3050, 3074], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: easingFromToken("smooth_out") })) * 120}px)`,
              opacity: interpolate(frame, [3050, 3074], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: easingFromToken("smooth_out") }),
              zIndex: 20,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontFamily: FONT_MONO, fontSize: 18, color: COLORS.cream }}>PV-07 · Peach</div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 13, color: tierColor(pv.risk.tier) }}>
                {pv.risk.tier.toUpperCase()}
              </div>
            </div>
            <div style={{ fontFamily: FONT_BODY, fontSize: 13, color: COLORS.slate, marginTop: 2 }}>{pv.name}</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 16 }}>
              {[
                ["Risk", `${pv.risk.score}/100`],
                ["Canopy", `${pv.risk.canopy_temp_f}°F`],
                ["Threshold", `${pv.risk.threshold_f}°F`],
                ["Exceed", `${pv.risk.exceedance_hours}h`],
                ["Humidity", `${pv.risk.humidity_pct}%`],
                ["Heat idx", `${Math.round(pv.risk.heat_index_f)}°F`],
              ].map(([k, v]) => (
                <div key={k} style={{ background: "rgba(10,15,30,0.6)", borderRadius: 10, padding: "8px 12px" }}>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 11, color: COLORS.slate, textTransform: "uppercase", letterSpacing: "0.08em" }}>{k}</div>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 18, color: COLORS.cream, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <LowerThird
          title="Live Field Map"
          subtitle="FortyGuard heatmap (tcm) · canopy heat risk, real orchard polygons"
          accent={COLORS.peach}
          from={10}
        />
        <ProgressBar />
      </MeshBackground>
    </AbsoluteFill>
  );
};

/** Local hex→rgb helper (deck.gl wants 0–255 int arrays). */
function hexToRgbArr(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}