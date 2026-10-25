# ShadowClip 0.1.23-rc8

## Clip editor

- Added an integrated trim editor for clips and recordings.
- Start and end frames are previewed directly in ShadowClip.
- Fast mode keeps the original encoded video and audio whenever a safe keyframe cut is possible.
- Frame-accurate mode re-encodes only the selected range.
- Edited media is saved as a new file by default, with an explicit option to replace the original.
- The editor is available from the Home last-clip panel, gallery cards, and gallery context menu.

## Faster saves

- OBS replay completion is detected with a shorter polling interval.
- Storage-limit scans now run in a throttled background worker instead of delaying clip and recording completion.
- FFmpeg replay output skips an extra encode when no temporal trim is required.

## Reliability

- Fast edits automatically fall back to frame-accurate export when stream copy cannot produce a decodable video stream.
- Edited MP4 files receive a fast-start index and remain seekable in Windows media players.
- Explicit custom HUD hotkeys such as Alt+Z are preserved across restarts.
