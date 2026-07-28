# ShadowClip 0.1.21-rc3

Closed-test release candidate with safer OBS source switching.

## Changes since 0.1.21-rc2

- OBS no longer keeps Game Capture and Display Capture visible at the same time.
- Browser/Desktop capture now enables Display Capture only.
- Fullscreen games and Minecraft/OpenGL contexts now enable Game Capture only.
- This avoids black OBS source layers covering the intended capture source.
- OBS Display Capture now receives an explicit monitor id such as `\\.\DISPLAY1` instead of staying on the invalid `DUMMY` monitor.
- Desktop shell processes such as `ApplicationFrameHost.exe` are kept on Display Capture instead of being sent to OBS Game Capture.
- The replay watchdog still refreshes the source mode while replay is running.

## Test focus

- Minecraft fullscreen after starting replay from the desktop/control center.
- Chrome or Edge YouTube playback after switching away from Minecraft.
- Switching between a browser and a fullscreen game while replay is already active.
