/**
 * Root.tsx — Remotion composition registry.
 *
 * Each scene is its own composition (fast iteration in Studio) and a
 * `CoolChainMaster` Sequences them into the 300s master at 60fps.
 * Scene timing comes from design_tokens.scenes + the 300s budget:
 *   Hook 30s → Field Map 60s → Alert 60s → Corridor 60s → KPI 45s → Scale 45s
 *
 * Sequences only — no loops. Crossfades land in P4 (@remotion/transitions).
 *
 * Caption system (Employee C):
 *   • `CoolChainWithCaptions` — master + burned-in `CaptionOverlay` (submission
 *     MP4). ProgressBar/SceneDots are already rendered by every scene inside
 *     `CoolChainMaster`, so they are NOT re-added at the top level (avoids
 *     double-draw).
 *   • `CoolChainRecording` — same composition with the `ClickTrack` visual
 *     metronome for the voiceover recording session (not in the submission).
 */
import React from "react";
import { Composition, Sequence } from "remotion";
import { CANVAS_HEIGHT, CANVAS_WIDTH, FPS, MASTER_FRAMES, SCENES } from "./design/theme";
import { Hook } from "./scenes/Hook";
import { FieldMap } from "./scenes/FieldMap";
import { HarvestAlert } from "./scenes/HarvestAlert";
import { Corridor } from "./scenes/Corridor";
import { KPI } from "./scenes/KPI";
import { Scale } from "./scenes/Scale";
import { CaptionOverlay } from "./design/components/CaptionOverlay";
import { ClickTrack } from "./design/components/ClickTrack";
import { CAPTIONS, TIMING } from "./data/fixtures";

const sceneComponents: Record<string, React.FC> = {
  Hook,
  FieldMap,
  HarvestAlert,
  Corridor,
  KPI,
  Scale,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {SCENES.map((s) => {
        const Cmp = sceneComponents[s.name];
        return (
          <Composition
            key={s.name}
            id={s.name}
            component={Cmp}
            durationInFrames={s.durationInFrames}
            fps={FPS}
            width={CANVAS_WIDTH}
            height={CANVAS_HEIGHT}
          />
        );
      })}

      {/* Master: 300s, back-to-back Sequences */}
      <Composition
        id="CoolChainMaster"
        component={CoolChainMaster}
        durationInFrames={MASTER_FRAMES}
        fps={FPS}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
      />

      {/* Master + burned-in captions (submission MP4) */}
      <Composition
        id="CoolChainWithCaptions"
        component={CoolChainWithCaptions}
        durationInFrames={MASTER_FRAMES}
        fps={FPS}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
      />

      {/* Master + karaoke captions (word-level peach highlight) */}
      <Composition
        id="CoolChainKaraoke"
        component={() => <CoolChainWithCaptions karaoke />}
        durationInFrames={MASTER_FRAMES}
        fps={FPS}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
      />

      {/* Master + captions + visual clicktrack (voiceover recording session) */}
      <Composition
        id="CoolChainRecording"
        component={() => <CoolChainWithCaptions recording />}
        durationInFrames={MASTER_FRAMES}
        fps={FPS}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
      />
    </>
  );
};

const CoolChainMaster: React.FC = () => {
  let offset = 0;
  return (
    <>
      {SCENES.map((s) => {
        const Cmp = sceneComponents[s.name];
        const el = (
          <Sequence key={s.name} from={offset} durationInFrames={s.durationInFrames} name={s.name}>
            <Cmp />
          </Sequence>
        );
        offset += s.durationInFrames;
        return el;
      })}
    </>
  );
};

interface MasterWithCaptionsProps {
  /** Voiceover-recording mode: adds the ClickTrack visual metronome. */
  recording?: boolean;
  /** Karaoke mode: highlight the current word in peach (word-level timing). */
  karaoke?: boolean;
}

export const CoolChainWithCaptions: React.FC<MasterWithCaptionsProps> = ({
  recording = false,
  karaoke = false,
}) => {
  return (
    <>
      <CoolChainMaster />
      {/* Burned-in captions — mounted outside per-scene Sequences so
          useCurrentFrame() stays on the master timeline (seconds 0–300). */}
      <CaptionOverlay captions={CAPTIONS} karaoke={karaoke} />
      {/* ProgressBar + scene dots are already inside every scene (no double-draw). */}
      {recording ? <ClickTrack timing={TIMING} /> : null}
    </>
  );
};