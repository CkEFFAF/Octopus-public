# Animated experts review, 2026-10-14

Reviewer: independent GPT-6 agent. Author model not supplied, so cross-model independence is not established.

Scope: current animated expert implementation against spec 0013. Source code was inspected without modification or Git operations.

Verdict: Approve. The sole major finding is resolved. No remaining blocker identified in this focused review.

## Resolved major

### Project member avatars bypass sprite rendering

Locations at initial review: `dashboard/src/pages/Chat/components/ProjectRoomBar.tsx:108`, `dashboard/src/pages/Chat/components/ProjectRoomBar.tsx:187`, `dashboard/src/pages/Projects/index.tsx:221`.

These entries pass `member.icon_url` directly to Ant Design Avatar. Selecting an animal now persists a URL such as `/expert-animations/fox.webp`, which is the entire 1536 by 1024 sheet. Opening the project member list or room member picker therefore displays the whole sheet instead of the selected animal. Existing bundled SVG paths also retain the old artwork on these surfaces.

Use the shared ExpertAgentAvatar or ExpertIcon renderer here, preserving custom uploaded image behavior. Check the project header and market card for the same direct URL pattern.

Resolution verified by source inspection: both ProjectRoomBar member entries and the Projects member list now supply an ExpertIcon React node to Ant Design Avatar. The busy flag selects the running pose. ExpertMarketTab also uses ExpertIcon. Local selected and bundled animal URLs therefore reach the sprite renderer, while uploaded and third-party image URLs retain the existing image renderer. No application code or Git state was modified during this follow-up.

## Evidence and boundaries

All ten atlases contain 24 frames each. Independently compared all 240 crop path strings with the supplied HTML and confirmed every path is present verbatim. Inspected frame timings, the 28 phase aliases and rabbit/red panda exceptions against the supplied animation code. No discrepancy found in these contracts.

Inspected completion expiration, session key guards, cancellation wiring, pending approval precedence, latest-user-turn isolation, lifecycle state mapping, character persistence through the existing icon_url PATCH, uploaded image priority, static historical message avatars, reduced motion, page visibility and offscreen timer cleanup. No additional blocker identified in those paths.

This review does not substitute for visual verification or claim independent test suite execution. The parent task owns runtime UI checks, targeted tests, typecheck and build evidence.
