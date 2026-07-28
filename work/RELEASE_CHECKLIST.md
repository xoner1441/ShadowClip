# ShadowClip Release Checklist

## Automated

- [ ] Python source compiles.
- [ ] Release unit tests pass.
- [ ] App, portable package, and installer versions match.
- [ ] Portable defaults open the first-run setup and contain no fixed install ID.
- [ ] OBS and FFmpeg executables and license notices are present.
- [ ] Package contains no PDB files, caches, crash dumps, or runtime logs.
- [ ] Installer SHA256 is generated.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\work\tools\Build-ShadowClipRelease.ps1 -Force
```

## Manual acceptance

- [ ] Fresh install opens the setup wizard.
- [ ] Update from the previous release preserves settings and relaunches once.
- [ ] Windows restart produces one tray icon and starts replay when configured.
- [ ] A 30-second clip has video, microphone, desktop audio, and correct A/V sync.
- [ ] A two-minute clip reaches the configured duration without unbounded RAM growth.
- [ ] Normal recording starts, stops, and remains synchronized.
- [ ] HUD, toast, recording indicator, tray menu, and standalone hotkeys respond.
- [ ] Minecraft/OpenGL, one anti-cheat game, one browser, and one non-native-resolution game capture correctly.
- [ ] Capture self-test and beta diagnostic export complete.
- [ ] Uninstall removes the app while leaving user clips untouched.

## Publish

- [ ] Review `RELEASE_NOTES_0.1.22.md`.
- [ ] Upload `ShadowClipSetup-0.1.22.exe` and its SHA256.
- [ ] Publish GitHub tag `v0.1.22` as a normal release, not a prerelease.
- [ ] Confirm an older installed version detects `0.1.22`.
