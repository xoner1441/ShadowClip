# ShadowClip 0.1.21-rc5

Closed-test release candidate focused on Minecraft Java OBS capture.

## Changes since 0.1.21-rc4

- Minecraft/Java foreground windows now use OBS `specific window` Game Capture instead of generic `any fullscreen` Game Capture.
- ShadowClip now passes the Minecraft window title, window class, and executable name to OBS, with executable fallback matching enabled.
- Minecraft-specific Game Capture enables OBS multi-adapter compatibility mode to reduce black frames on mixed-GPU/OpenGL setups.
- Added `Minecraft OBS mode` in the control center and HUD settings:
  - `specific_game`: new default, specific Java/Minecraft Game Capture.
  - `display`: display-capture fallback for setups where Java Game Capture stays black.
  - `any_fullscreen`: old rc4 behavior.
- The OBS watchdog refreshes the Minecraft window selector even when the capture mode itself has not changed.

## Test focus

- Minecraft Java fullscreen and windowed/borderless with `Minecraft OBS mode = specific_game`.
- If the clip is still black, switch `Minecraft OBS mode` to `display`, save settings, restart replay, and test again.
- Regression check: League/Rust should still use regular OBS Game Capture.
