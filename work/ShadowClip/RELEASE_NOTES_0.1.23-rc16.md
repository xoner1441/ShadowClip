# ShadowClip 0.1.23-rc16

## Native-resolution widescreen output

- ShadowClip now queries the monitor's preferred hardware mode through the Windows Display Configuration API.
- Temporary exclusive-fullscreen modes no longer replace the OBS canvas size, even when Windows also exposes them as the registry display mode.
- A 1440x1080 game source on a 1920x1080 monitor is stretched to the full 1920x1080 output without player-generated side bars.
- The resolved output size is locked for the complete ShadowClip session to prevent later display-mode changes from shrinking the canvas.
- Multi-monitor selection is matched through the Windows GDI display device name.

## Reliable playback timelines

- Raw OBS files remain hidden until seek finalization has completed.
- Finalization waits for stable files, discards damaged trailing packets, and removes malformed OBS metadata.

## Reliability carried forward

- Persistent Replay and recording indicators remain fully click-through.
- UI log and gallery caches stay bounded for stable long-session resource use.
