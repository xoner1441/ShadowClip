# ShadowClip 0.1.21-rc8

Closed-test release candidate focused on hardware encoder selection.

## Changes since 0.1.21-rc7

- Added hardware encoder auto-selection for NVIDIA NVENC, AMD AMF, and Intel QuickSync.
- ShadowClip now checks installed GPU adapters and prefers dedicated NVIDIA/AMD encoders before Intel QuickSync, then falls back to CPU x264.
- The OBS backend now writes the matching simple encoder (`nvenc`, `amd`, `qsv`, or `x264`) into the portable OBS profile.
- The FFmpeg fallback path now has explicit H.264 argument sets for NVENC, AMF, QSV, and x264.
- Hardware encoder failure retry is now generic, so any auto-selected hardware encoder can fall back to CPU x264.
- The main control center and HUD settings now expose `h264_amf` and `h264_qsv` in the encoder list.

## Test focus

- On an NVIDIA system, start replay and confirm the log says `Selected hardware encoder: NVIDIA NVENC (H.264).`
- Save a clip in Rust/League/Minecraft and confirm scaling, audio, and clip folder grouping still behave as in rc7.
- On AMD-only or Intel-only test systems, confirm the log picks AMD AMF or Intel QuickSync instead of NVENC.
