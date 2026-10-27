# ShadowClip 0.1.23-rc13

## Click-through status overlays

- Persistent Replay and recording icons are now fully mouse-transparent and no longer block clicks in games.
- Native styles are applied to both Tkinter's inner window and the real Windows `TkTopLevel` wrapper.
- Hit testing explicitly returns `HTTRANSPARENT`, while `WS_EX_TRANSPARENT` and `WS_EX_NOACTIVATE` prevent focus changes.
- Interactive HUD mode still restores normal mouse input when click-through mode is disabled.

## Reliability carried forward

- Includes immediate, seekable Faststart MP4 finalization for new clips and recordings.
- Includes bounded UI log and gallery caches for stable long-session RAM use.
- Includes restored event toasts, exact Explorer file selection, and compact Replay/recording status icons.
