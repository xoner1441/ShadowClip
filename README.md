# ShadowClip

ShadowClip is a Windows replay buffer and clip recorder with a bundled private OBS runtime. It supports game and display capture, hardware encoding, microphone and desktop audio, normal recordings, a clip gallery, customizable hotkeys, HUD feedback, per-game profiles, diagnostics, and automatic updates.

## Source

- Application: `work/ShadowClip/ShadowClip.py`
- Installer: `work/installer`
- Release tools and tests: `work/tools` and `work/tests`
- Current release notes: `work/ShadowClip/RELEASE_NOTES_0.1.23-rc9.md`

OBS and FFmpeg binaries, local build environments, generated packages, and installers are intentionally excluded from Git history. Public release installers must retain `THIRD_PARTY_NOTICES.md` and the bundled license files.

## Build

The release build requires the local OBS/FFmpeg runtime inputs and Inno Setup 6:

```powershell
powershell -ExecutionPolicy Bypass -File .\work\tools\Build-ShadowClipRelease.ps1 -Force
```

The command builds the application, assembles the portable package, creates the installer, runs release validation, and writes SHA256 checksums below `outputs`.

See `work/RELEASE_CHECKLIST.md` for the manual acceptance tests required before publishing.
