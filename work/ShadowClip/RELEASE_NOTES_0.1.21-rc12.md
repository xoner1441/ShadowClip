# ShadowClip 0.1.21-rc12

- Added optional per-game/app profiles for capture source, OBS/FFmpeg backend, clip length, FPS, encoder, bitrate, quality, container, and audio sync offsets.
- Added `Use per-game profiles`, `Save Game Profile`, and `Delete Profile` controls in the main window and HUD settings.
- Profiles are applied automatically before replay, clip save, and normal-recording actions.
- Setup health check and debug reports now include game-profile status and the current detected profile context.
- New installs enable per-game profiles by default while preserving existing user config during upgrades.
