# ShadowClip 0.1.22

ShadowClip 0.1.22 is the first stable package after the 0.1.21 release-candidate cycle.

## Highlights

- Instant Replay and full recording through the bundled private OBS runtime.
- Automatic NVIDIA NVENC, AMD AMF, Intel QuickSync, or CPU encoder selection.
- Automatic bitrate and replay-memory sizing from resolution, FPS, and clip length.
- Microphone and desktop audio capture with independent clip and recording sync offsets.
- Game/app folders, per-game profiles, clip gallery, thumbnails, and last-clip preview.
- Customizable global hotkeys, tray controls, HUD, event toasts, and recording indicator.
- First-run setup, capture self-test, one-click repairs, diagnostics, and GitHub updates.

## Capture stability

- General game/display fallback strategy for black frames and unsupported game hooks.
- Browser display-capture fallback for GPU-rendered browser content.
- Full-canvas source fitting for non-native game resolutions.
- Minecraft/OpenGL safeguards that avoid unsafe parallel Windows Graphics Capture probes.
- OBS cold-start readiness guard and serialized startup to prevent the startup crash seen after Windows login.
- One automatic private OBS restart when startup fails before the video frontend is ready.

## Release hardening

- Correct semantic ordering between release candidates and final releases.
- Clean fresh-install and portable defaults without a shared diagnostic install ID.
- Version metadata embedded in `ShadowClip.exe` and the installer.
- Reproducible build, package validation, license checks, and SHA256 output.

Existing settings are preserved when updating through the installer.
