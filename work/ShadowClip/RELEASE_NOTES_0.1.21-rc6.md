# ShadowClip 0.1.21-rc6

Closed-test release candidate focused on OBS scaling stability for non-native game resolutions.

## Changes since 0.1.21-rc5

- OBS scene item scaling now reads the live OBS canvas size before applying the full-canvas transform.
- The OBS replay watchdog repairs active source scaling when OBS or a game changes the source bounds during a running replay session.
- This targets Rust and similar games running at non-native resolutions such as 1440x1080 while OBS is still using a 1920x1080 canvas.
- Added a log line when ShadowClip repairs an OBS source from the wrong bounds back to the active canvas size.

## Test focus

- Rust at 1440x1080 while replay is already running.
- Switching between desktop resolution and in-game stretched/non-native resolution.
- Regression check: Minecraft Java specific-window capture should keep working.
