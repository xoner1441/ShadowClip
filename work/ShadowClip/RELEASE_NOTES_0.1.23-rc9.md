# ShadowClip 0.1.23-rc9

## Restored capture feedback

- Restored compact in-game feedback icons for saved clips, replay state, recordings, and failures.
- Replay and recording status can be shown together without covering gameplay with a large text panel.
- Restored the custom Pulse Deep sound set and added a preview action in HUD settings.
- Replay start, replay stop, recording start, recording stop, clip saves, and clip-save failures now update feedback consistently.

## Gallery and overlays

- Preserved clip search, game/app filtering, media-type filtering, sorting, thumbnails, and exact-file reveal in Explorer.
- Added release regression checks so gallery discovery controls cannot silently disappear from future packages.
- Desktop-overlay capture is enabled once for existing installations and by default for new installations, while later user changes remain respected.

## Clip editor and faster saves

- Includes the integrated trim editor for clips and recordings with fast and frame-accurate export modes.
- Storage-limit cleanup runs in the background so clip and recording completion is not delayed.
- OBS replay completion polling is faster, and FFmpeg avoids an extra encode when a direct stream copy is valid.
