# ShadowClip

ShadowClip is a Windows clip recorder MVP. It records the full desktop, one monitor, or a selected window/game title through FFmpeg.

## Features

- Replay buffer for the last N seconds
- Default HUD hotkey: `F8`
- Default save clip hotkey: `F9`
- Default start/stop replay hotkey: `F10`
- Default start/stop normal recording hotkey: `F11`
- Full desktop, single-monitor, and window/game-title capture
- Automatic DDA backend for one-monitor capture, with GDI fallback
- Bundled OBS backend for fullscreen/game-capture tests, recommended for games protected by anti-cheat or exclusive fullscreen behavior
- Hardware encoder auto-selection for NVIDIA NVENC, AMD AMF, and Intel QuickSync, with CPU fallback
- Automatic video bitrate calculation from resolution, frame rate, and a Balanced/High/Ultra preset
- Quality mode or target-bitrate mode with configurable target and max Mbps
- Automatic OBS replay RAM limit based on clip length and target bitrate, with optional manual override
- Automatic OBS browser fallback for Chrome, Edge, Firefox, Brave, Opera, Vivaldi, and Chromium-based browsers to avoid black video frames on GPU-rendered pages
- Automatic OBS black-screen recovery with a live display layer, final-scene frame checks, DXGI-to-WGC switching, exact-window Game Capture retry, and per-session strategy learning
- Optional WGC desktop-overlay capture for Xbox Game Bar, Crosshair X, and other visible Windows-composited overlays, with automatic Game Capture fallback
- Optional per-game/app profiles for capture source, backend, clip length, FPS, encoder, bitrate, quality, container, and audio sync offsets
- Separate WASAPI mic and desktop/loopback audio capture for replay clips
- Mic + desktop audio mixing when both devices are enabled
- Exact-duration export trim after replay segments are joined
- Optional replay-window reset after each saved clip; later clips save only new replay time, even if it is shorter than the max clip length
- Automatic replay recovery when FFmpeg exits unexpectedly, with DDA-to-GDI fallback for fullscreen display-access loss
- GitHub Releases update checker with optional installer download and SHA256 verification when available
- First-time setup wizard with automatic OBS, FFmpeg, GPU encoder, monitor, audio-device, and output-folder detection
- Guided capture, audio, FPS, clip-length, startup, automatic bitrate, and replay-RAM configuration for new installations
- One-click capture self-test that records a fresh ten-second replay and checks the saved file, video stream, duration, resolution, FPS, black-screen ratio, audio stream, A/V start timing, and audio activity
- Actionable capture-test results with direct access to the test clip and recommendations for OBS, audio-device, encoder, resolution, and timing problems
- Repair buttons in Setup Check for bitrate, replay RAM, encoder selection, bundled runtimes, audio devices, monitor selection, and replay state
- Privacy-safe beta diagnostic ZIP with an anonymous support ID, redacted Windows identity/paths, setup checks, capture-test results, and recent logs
- Setup health check for FFmpeg, OBS, hardware encoder, replay state, audio devices, output folder, and OBS replay RAM
- Debug report ZIP export with redacted config, health-check results, UI log, and recent runtime logs
- Tray icon with background mode, quick actions, and clip-saved notifications
- Windows autostart option, launching minimized to tray
- Open the last clip or reveal it in Explorer from the app or tray menu
- Built-in clip library with generated video thumbnails, game/app and media-type filters, search, date/name/size sorting, and incremental loading
- Open, reveal, rename, or move saved clips and recordings to the Windows Recycle Bin directly in ShadowClip
- In-HUD clip gallery with recent clips, play buttons, reveal buttons, and a `Play Last` action
- Live normal-recording timer and file size in the control center, HUD recording tile, and optional bottom-right REC indicator
- Optional game/app folders for clips and recordings, similar to ShadowPlay's game grouping
- Friendly game and app names across new folders, gallery filters, profiles, and diagnostics, including Minecraft, Rust, League of Legends, Rainbow Six Siege, Fortnite, VALORANT, and common browsers
- Optional storage limit with cleanup of the oldest clips and recordings
- Optional replay-buffer start when the app launches
- Refreshed control-center layout with live status fields for replay, recording, audio, source, and storage
- Height-aware module scrolling on Home, Capture, Video, Audio, HUD, Hotkeys, Storage, and Updates; scrollbars appear only when content no longer fits
- Clickable Replay status card on Home for starting and stopping Instant Replay, with hover and keyboard activation
- Icon-enhanced controls, settings labels, and HUD actions
- ShadowPlay-style HUD overlay for replay, clip saving, recording, gallery, audio toggles, and in-HUD settings
- ShadowPlay-style event overlay when clips are saved or full recordings start/stop, with configurable duration and position
- Robust Windows folder/file pickers for output and FFmpeg paths
- Custom ShadowClip app/tray icon
- Local JSON config

## Setup

1. Run `ShadowClip.exe`.
2. Complete the first-time setup wizard. It detects the bundled tools and recommends settings for the current PC.
3. Start Instant Replay, or enable automatic replay startup in the wizard.
4. Press the save clip hotkey, by default `F9`, or `Save Clip`.

The wizard opens automatically only for a fresh installation. Existing configurations are preserved during updates. Open `Updates > Setup wizard` to run it again at any time.

After setup, open `Updates > Capture test` for an end-to-end recording check. ShadowClip temporarily restarts Instant Replay with a ten-second test buffer, saves the result below `ShadowClip Tests`, validates it with FFprobe/FFmpeg, and then restores the previous replay running state and normal settings. Keep moving content visible, play desktop audio, and speak during the countdown for a meaningful result.

`Updates > Check setup` presents individual repair buttons for supported problems. `Updates > Beta report` creates a shareable ZIP and shows a stable anonymous support ID. Windows user/computer names, window titles, and personal directory roots are removed or replaced before export; review the ZIP before sharing if custom device or profile names contain sensitive text.

Closing the window hides ShadowClip to the tray. Use the tray icon menu to reopen it or exit fully.
Press the HUD hotkey, by default `F8`, to open or close the ShadowClip HUD overlay.
Press `Settings` in the HUD to change capture, video, audio, storage, startup, and keybind settings without opening the main control-center window.
The HUD `Interface` settings control toast duration/position, gallery size, closing behavior after saving a clip, and the recording indicator.
Click a keybind field in the HUD settings page, press the new shortcut, then press `Save` to re-register the global hotkeys.
Enable `Use per-game profiles`, focus a game/app or select a Window/Game title, then press `Save Game Profile` to store the current capture and video settings for that context. ShadowClip reapplies the matching profile before replay, clip, and recording actions.
Enable `Start with Windows` and save settings to add ShadowClip to the current user's Windows startup list.
Enable `Start replay on launch` if ShadowClip should begin buffering automatically after the app starts.
Enable `Check updates on launch` to let ShadowClip look for newer GitHub releases on startup. Downloads and installation always require confirmation.
Updater installs run in a quiet update-safe mode: ShadowClip stops capture, closes, waits for the installer to finish, waits a few seconds more, then relaunches. This avoids first-start races with PyInstaller's temporary runtime extraction.

The main desktop window uses a dark Control Center layout with sidebar pages for the core workflow, clip library, capture/video/audio settings, HUD and hotkeys, storage, updates, and logs. The `Clips` page scans supported video files below the output folder, including OBS `Replay` files and normal recordings. Preview images and media metadata are generated in the background so large libraries remain responsive.

Capture, Video, Audio, HUD, Storage, Updates, Logs, and Hotkeys use grouped dark settings panels with consistent controls. Settings pages show when changes have not been saved. The Storage page scrolls with the mouse wheel anywhere over its content when the window is too short to show every option.

Hotkeys can be configured as full combinations or standalone keys. Standalone keys are handled by ShadowClip's low-level keyboard hook so they can trigger actions without requiring Ctrl, Alt, Shift, or Win.

The packaged release already includes FFmpeg in `tools\ffmpeg`. If you build a minimal package without FFmpeg, run `Install-FFmpeg.ps1` from the app folder. If PowerShell blocks the setup script, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-FFmpeg.ps1
```

## OBS backend

ShadowClip can start a portable OBS runtime through obs-websocket and use OBS Game Capture for replay clips and normal recordings. This is the recommended backend for fullscreen games where FFmpeg desktop capture records a stale loading screen, black frames, or loses access after a display-mode switch.

The packaged release already includes the portable OBS runtime at:

```text
ShadowClip\tools\obs\bin\64bit\obs64.exe
```

If you build a package without bundled OBS, set the `OBS` path in the UI to `obs64.exe`. Choose backend `obs`, start replay, focus the game, and save a clip. ShadowClip writes an OBS `ShadowClip` profile before launch so replay buffer support is enabled.

The default `Auto OBS replay RAM` mode calculates the replay memory limit from clip length and target bitrate, then adds safety padding and rounds to the next 64 MB step. The default 30-second, 35 Mbps target uses `256 MB`; a 120-second, 35 Mbps target uses `640 MB`. Disable auto mode only if you want to pin a manual `OBS replay RAM MB` value. ShadowClip selects a hardware H.264 encoder automatically in the order NVIDIA NVENC, AMD AMF, Intel QuickSync, then CPU x264 fallback.

The default `Auto bitrate` mode calculates target/max Mbps from the selected capture resolution, FPS, and quality preset. `High` uses roughly `35 Mbps` for 1080p60, `70 Mbps` for 1080p120, and scales up or down with the pixel count and frame rate. `Balanced` creates smaller files, while `Ultra` gives fast-motion clips more headroom. Disable `Auto bitrate` only if you want to tune `Bitrate mode`, `Target Mbps`, and `Max Mbps` manually.

When a browser such as Chrome, Edge, Firefox, Brave, Opera, Vivaldi, or another Chromium-based browser is foreground, the OBS backend starts with display capture. Fullscreen games use OBS Game Capture while a monitor source remains live underneath it. A failed transparent game hook therefore falls through to the desktop picture immediately. ShadowClip also samples the final OBS scene at low resolution: when consecutive frames are effectively black, it disables a blocking Game Capture layer, switches Automatic/DXGI display capture to Windows Graphics Capture (WGC), and can retry Game Capture against the exact foreground window. A working strategy is remembered for that application during the current session. After recovery, ShadowClip resets the replay window so later clips do not include the detected black frames; a clip request is rejected while the current picture is demonstrably black instead of saving a useless file. Minecraft/Java still supports its specific-window preference in settings. OBS scene items are stretched to the live canvas to avoid black bars when a game renders at a non-native resolution such as 1440x1080 while OBS outputs 1920x1080. If the selected monitor resolution changes while replay is running, the OBS watchdog refreshes the canvas and restarts the replay buffer so future clips use the new resolution.

Enable `Capture desktop overlays (WGC)` on the Capture page or in HUD settings when Xbox Game Bar, Crosshair X, or another visible desktop overlay should appear in clips. This mode forces the OBS backend and places WGC monitor capture above Game Capture so the final Windows desktop composition is recorded. If that WGC layer is black in exclusive fullscreen, ShadowClip removes it and preserves the underlying game capture. Applications can explicitly exclude their windows from all capture APIs; such protected overlays cannot be forced into a recording by ShadowClip.

If OBS or FFmpeg are bundled with a public installer, keep `THIRD_PARTY_NOTICES.md` and the bundled license files in the release materials.

## Audio notes

Replay clips capture microphone and desktop/system audio through native Windows WASAPI in separate audio threads, then mix those tracks into the saved clip. This keeps FFmpeg's live replay process focused on video and avoids Stereo Mix, VB-Cable, or Voicemeeter. Scan audio devices, enable `Mic` and/or `Desktop`, then choose the matching devices. Leaving the WASAPI desktop device empty uses the Windows default output device.

If audio is still offset on a specific system, use `Audio offset ms`: negative values move audio earlier, positive values move audio later. A good first test for late audio is `-2000`.

## Game capture notes

Window/game-title capture works best with games running windowed or borderless fullscreen. Exclusive fullscreen, HDR, anti-cheat, and some Vulkan/DirectX paths may not expose frames cleanly through FFmpeg `gdigrab`.

For games that make the replay buffer stop when they enter fullscreen, such as games protected by strict anti-cheat or display-mode switching, use `One monitor` capture with backend `auto` first. ShadowClip will try DDA for smooth capture and automatically fall back to GDI desktop capture if Windows reports DDA display-access loss. If that still fails or records a black frame, switch the game to borderless fullscreen/windowed fullscreen and try backend `gdigrab`.

For stubborn fullscreen games, use backend `obs`. It uses OBS Game Capture with the anti-cheat compatibility hook, a live monitor fallback, and automatic DXGI/WGC recovery. No capture API can guarantee access to DRM-protected video, secure desktops, or a game that deliberately blocks every available path, but ordinary unsupported hooks and GPU-surface black screens no longer require a hardcoded per-game exception.

## Third-party notices

The release build bundles OBS Studio and FFmpeg. See `THIRD_PARTY_NOTICES.md` for tested component versions, project links, and license-file locations inside the installed app folder.

## Output

By default, clips and recordings are saved to:

```text
%USERPROFILE%\Videos\ShadowClip
```

When `Organize by game/app` is enabled, ShadowClip creates subfolders from the active app or selected window/game title, for example:

```text
F:\ShadowClip\GameName\clip_2026-06-22_18-30-00.mp4
```

For monitor or all-screen capture, use the hotkey while the game is focused so the clip lands in the matching game/app folder. If ShadowClip cannot detect a useful foreground app, it uses `Desktop`.

Set `Max storage GB` above `0` to let ShadowClip delete the oldest clips and recordings after new files are saved. The newest file is kept even if the limit is very small. Use `Clean Storage` to apply the limit manually.

Per-game profiles are stored in `shadowclip.config.json` and are keyed by the foreground process when available, for example `RustClient`, `FortniteClient-Win64-Shipping`, `javaw`, or `chrome`. Use `Delete Profile` while the same app/window context is active to remove a saved profile.

The replay buffer and FFmpeg logs are written to:

```text
%LOCALAPPDATA%\ShadowClip
```

## Updates

ShadowClip checks GitHub releases at:

```text
https://github.com/xoner1441/ShadowClip/releases
```

For auto-update discovery, publish a release with a higher tag such as `v0.1.3` and upload an installer asset named like:

```text
ShadowClipSetup-0.1.3.exe
```
