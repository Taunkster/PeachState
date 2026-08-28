/**
 * index.ts — Remotion entry point.
 *
 * Register the root composition registry; the Remotion CLI renders
 * compositions by id (see README.md → npm run render).
 */
import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);