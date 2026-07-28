# ShadowClip 0.1.21-rc2

Closed-test release candidate with an OBS browser capture fix.

## Changes since 0.1.21-rc1

- Added automatic browser detection for Chrome, Edge, Firefox, Brave, Opera, Vivaldi, Chromium-based browsers, and common Firefox forks.
- When a browser is foreground while the OBS backend is active, ShadowClip switches the OBS scene to display capture only. This avoids black video frames caused by browser/GPU surfaces covering the monitor fallback.
- When focus returns to a non-browser app, ShadowClip switches back to game capture with monitor fallback.
- The replay watchdog now updates the OBS scene source mode every two seconds while replay is running.
- Saving an OBS replay clip now refreshes the source mode once before asking OBS to save the buffer.

## Still worth testing

- YouTube playback in Chrome/Edge with hardware acceleration enabled.
- YouTube playback in Chrome/Edge with hardware acceleration disabled, if the first test still shows black video.
- Normal fullscreen games after switching away from a browser, to confirm game capture returns automatically.
