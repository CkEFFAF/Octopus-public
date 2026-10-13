# Expert animation artwork

Extracted from the user's `Qunqi_Animation_Preview_v3_smoother.html` for integration into Octopus. Ten 1536 × 1024 atlases each contain 24 poses. WebP encoding is lossless; the source PNGs are not duplicated in the repository.

The source's silhouette clips, frame bounds, scale and portrait bounds are preserved in `dashboard/src/components/AnimatedExpertAvatar/atlas.json`. The renderer applies the silhouette mask to exclude the atlas background. Action aliases and the source's rabbit/red panda exceptions are in `model.ts`.

The preview's application bundle, embedded libraries, local-storage demo settings and simulated execution state machine are not included. Actual Octopus chat and runtime state drives playback.
