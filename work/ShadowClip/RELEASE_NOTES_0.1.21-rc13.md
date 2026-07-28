# ShadowClip 0.1.21-rc13

- Added `Auto bitrate` for video capture. ShadowClip now calculates target/max Mbps from selected resolution, FPS, and a Balanced/High/Ultra preset.
- New installs default to `Auto bitrate: ON`, preset `high`, and target-bitrate mode.
- Auto OBS replay RAM now follows the automatically calculated bitrate, so changing FPS or clip length updates both quality and replay-buffer memory.
- Added Auto bitrate status to the setup health check.
- Per-game profiles now store the Auto bitrate switch and preset, so individual games can keep their own FPS/quality behavior.
