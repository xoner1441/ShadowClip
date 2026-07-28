# ShadowClip 0.1.21-rc4

Closed-test release candidate with OBS canvas stretch for non-native game resolutions.

## Changes since 0.1.21-rc3

- OBS Game Capture and Display Capture scene items are now stretched to the full ShadowClip canvas.
- This removes black bars when a game is captured at a different render resolution than the selected monitor, for example 1440x1080 inside a 1920x1080 canvas.
- Existing OBS scenes are repaired on startup/reconfigure, so old `scale: 1.0` scene item transforms should not persist after launching this version.
- The rc3 source switching remains in place: browsers/desktop use Display Capture only, fullscreen games and Minecraft/OpenGL contexts use Game Capture only.

## Test focus

- Rust or other games running at stretched/non-native resolutions such as 1440x1080.
- Minecraft fullscreen after switching between desktop/browser/game capture.
- Chrome or Edge YouTube playback to confirm browser display capture still fills the frame.
