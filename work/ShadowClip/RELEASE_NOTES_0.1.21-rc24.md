# ShadowClip 0.1.21-rc24

- Added a five-step first-time setup wizard for system checks, capture display, audio, video quality, and startup behavior.
- Added automatic detection of bundled OBS and FFmpeg, GPU hardware encoder, monitors, WASAPI microphones, desktop audio outputs, and output-folder access.
- Added automatic video bitrate and OBS replay-memory recommendations based on the selected monitor, FPS, clip length, and quality preset.
- Fresh installations now open the wizard automatically; existing installations keep their current configuration and skip it.
- Added a reusable Setup wizard action to the Updates page.
- Delayed automatic replay startup and update checks until first-time setup is complete.
- Corrected 64-bit Windows handle typing when the tray window class is released during shutdown.
