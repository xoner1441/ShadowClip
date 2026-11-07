# ShadowClip 0.1.23-rc14

## Resolution-safe widescreen capture

- OBS now keeps the normal Windows desktop resolution as its stable output canvas while a fullscreen game temporarily changes the display mode.
- Stretched resolutions such as 1440x1080 are expanded to the full 1920x1080 output instead of producing a 4:3 video with side bars.
- The selected monitor is resolved through its Windows display device, including multi-monitor setups.
- Existing full-canvas OBS source transforms are reapplied after capture-source or canvas recovery.

## Reliability carried forward

- Persistent Replay and recording indicators remain fully click-through.
- New MP4 clips and recordings are finalized as seekable Faststart files.
- UI log and gallery caches stay bounded for stable long-session resource use.
