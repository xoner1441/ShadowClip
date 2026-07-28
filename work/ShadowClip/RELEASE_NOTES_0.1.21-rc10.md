# ShadowClip 0.1.21-rc10

- Added `Auto OBS replay RAM`, enabled by default.
- OBS replay memory now updates from the selected clip length and target bitrate with safety padding and 64 MB rounding.
- The default 30-second, 35 Mbps replay target stays at 256 MB.
- A 120-second, 35 Mbps replay target now automatically uses 640 MB.
- The manual OBS replay RAM field is disabled while auto mode is active and becomes editable again when auto mode is turned off.
