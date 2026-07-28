# ShadowClip 0.1.21-rc31

- Fixed a repeatable OBS 32.1.2 crash at `win-capture.dll + 0x9D4B` seen across six Minecraft sessions.
- Removed live `GetSourceScreenshot` probes from replay and recording watchdogs so Minecraft's OpenGL hook can reconnect without a concurrent OBS screenshot request.
- Removed the live screenshot check and forced capture-source refresh immediately before saving an OBS replay.
- Added a Minecraft-safe path for the `specific_game` mode that uses Game Capture without a parallel WGC monitor layer.
- Kept WGC desktop-overlay capture available for display capture and other supported capture modes.
- Pinned OBS monitor capture to the monitor selected in ShadowClip instead of following short-lived foreground-window changes.
- Prevented identical OBS display and game input settings from being reapplied to active capture sources.
- Reduced unnecessary configuration and transform requests for disabled OBS sources.
- Added a startup log entry confirming that live screenshot health probes are disabled for win-capture stability.
