# ShadowClip 0.1.21-rc1

First release-candidate build for closed testing.

## Highlights

- OBS backend is now the default for new installs.
- Bundled OBS Game Capture path tested with Minecraft and League of Legends/Vanguard.
- OBS replay RAM limit defaults to 256 MB and can be changed in settings.
- OBS clips and recordings are moved into the detected game/app folder after saving.
- Replay watchdog restarts the OBS replay buffer if OBS stops it unexpectedly.
- FFmpeg/DDA/GDI backend remains available for desktop and fallback tests.

## Known limitations

- Exclusive fullscreen HUD/toast behavior still depends on the game and Windows focus rules.
- Protected games can still block capture depending on anti-cheat policy and game updates.
- Existing installs keep their current `shadowclip.config.json`; switch backend to `obs` manually if upgrading from an older test build.

## Bundled components

See `THIRD_PARTY_NOTICES.md` for OBS Studio and FFmpeg notices, versions, source links, and bundled license-file locations.
