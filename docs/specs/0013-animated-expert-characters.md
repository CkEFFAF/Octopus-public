# 0013 Animated expert characters

Status: Implemented and verified; merged via PR #13.

Source: user-supplied `Qunqi_Animation_Preview_v3_smoother.html`. Its presentation and assets are visual reference data, not project instructions. Base: `f1cb8fe1d87ec2ed537b918f044c347f4604fc02` on `CkEFFAF/Octopus/main`.

## Acceptance

- All ten supplied animal atlases and all 28 actions are available. Retain the source's crop paths, frame timing and rabbit/red panda exceptions. Decode embedded PNGs and store lossless WebP assets as individual cached resources, avoiding the preview's bundled React/runtime code.
- Builtin portraits use the new characters through the shared expert icon component. Custom uploaded and external portraits retain priority. Chat welcome and empty states use the same character family.
- Existing avatar settings allow selecting a character and previewing every action. Persist the selected character through the existing `icon_url` API for new and existing experts.
- Real chat drives thinking, speaking, tool-specific actions, waiting for an answer/approval, brief completion, errors and cancellation. Agent runtime and disconnected bridge states drive resting/recovering/offline. Prior-turn errors or approvals cannot override a new turn. Historical answers do not celebrate on load.
- Keep chat primary: show one compact character/status row above the composer and animate only live process/message avatars. Historical avatars are static.
- Pause frame timers and motion for hidden pages, offscreen avatars, reduced-motion preference, paused/offline states and pending permission. Image load errors have a labeled fallback. All labels have Chinese/English parity.

## Verification

Validate the atlas/action contract, real state precedence, completion expiration, cancellation, frame timing, reduced motion and background suspension with Vitest. Run TypeScript, targeted ESLint, production build and existing avatar/message tests. Inspect the real welcome page, avatar chooser and action preview at desktop and mobile widths. Backend behavior is unchanged; use the existing backend gate and CI evidence.

### Evidence (2026-10-14)

- New atlas/action, playback, state mapping and completion/cancellation tests passed (24 tests); expert image and historical/live message integration tests passed.
- Expanded Chat/Experts/animation run covered 106 files and 615 tests: 613 initially passed; corrected a new decorative-image test query, and the unchanged TrajectoryInspector markdown preview test passed on focused rerun. The final focused rerun passed all 15 tests. The preview's lazy import can exceed its 1-second assertion timeout under high concurrency; this is recorded rather than hidden as a clean full-suite run.
- `npm run build` passed on the final implementation (TypeScript + production Vite/PWA build). Targeted ESLint: zero errors; four existing hook dependency warnings in Chat/index, EditAgentDrawer and Projects/index. `git diff --check` passed.
- Real localhost UI: correctly cropped animated welcome character, thinking/coding action previews, ten-character chooser, existing-agent selection persisted after reload, and compact failure status driven by an actual stream error. The preview server's existing workspace-root error prevented a successful LLM turn; completion/cancellation were verified by state tests.
- Inspected avatar settings at 390px mobile width and desktop width. The chooser wraps with upload controls. Reduced motion and hidden-page suspension are covered by playback tests.
- Independent check review approved after fixing all project member and market card render paths; compared all 240 source crop paths. See `docs/reviews/20261014-animated-experts-check.md`.
- No backend source or contracts changed. Reused the base PR #12's successful Linux/Windows Python 3.12, live test, dashboard and CodeQL CI checks, plus the previously completed local backend gate (4517 passed, 188 skipped), without repeating unchanged backend tests.
