# ShadowClip 0.1.23-rc15

## Reliable playback timelines

- Raw OBS clips and recordings are now written to a hidden working directory and only appear in the library after seek finalization completes.
- Windows Media Player can no longer cache the unfinished Hybrid MP4 index under the final filename.
- Finalization waits for the OBS file to stop changing before remuxing it.
- Damaged trailing packets are discarded during stream-copy repair instead of leaving the entire timeline unusable.
- Malformed OBS metadata is no longer copied into the final MP4.
- The hidden working directory is excluded from the clip gallery and storage library.

## Resolution-safe widescreen capture

- OBS keeps the normal Windows desktop resolution as its output canvas while fullscreen games temporarily switch display modes.
- Stretched resolutions such as 1440x1080 fill a 1920x1080 output without permanent side bars.

## Reliability carried forward

- Persistent Replay and recording indicators remain fully click-through.
- UI log and gallery caches stay bounded for stable long-session resource use.
