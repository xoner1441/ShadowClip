# ShadowClip 0.1.21-rc7

Closed-test release candidate focused on OBS canvas updates after monitor resolution changes.

## Changes since 0.1.21-rc6

- The OBS replay watchdog now detects when the live OBS canvas no longer matches the selected monitor resolution.
- If the canvas stays stale after a resolution change, ShadowClip briefly restarts the OBS replay buffer and applies the new monitor size.
- This prevents clips from being saved as `1440x1080` after returning the monitor/game setup to `1920x1080`.
- Added log output for canvas mismatch detection and automatic canvas updates.

## Test focus

- Start replay while the selected monitor/game is `1440x1080`, then switch back to `1920x1080` and wait a few seconds.
- Save a clip and verify the video stream is `1920x1080`.
- Regression check: Rust stretched-resolution scaling and Minecraft Java capture should keep working.
