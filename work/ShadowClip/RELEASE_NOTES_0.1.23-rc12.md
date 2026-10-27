# ShadowClip 0.1.23-rc12

## Seekable clips and recordings

- OBS clips and normal recordings are now finalized into standard Faststart MP4 files after capture finishes.
- The conversion uses lossless stream copy, so video and audio are not re-encoded and quality is unchanged.
- Windows Media Player and Films & TV can use the timeline immediately without requiring a PC restart.
- OBS still records to crash-resistant Hybrid MP4 first; the original remains untouched until finalization succeeds.
- Long recording finalization runs in the background so the ShadowClip interface remains responsive.
- Existing Faststart MP4 files are detected and left unchanged.

## Lightweight long-session behavior

- The on-screen log now keeps a bounded history and processes bursts in small batches so worker output cannot stall the interface.
- In-memory gallery thumbnail and metadata caches are bounded to prevent gradual RAM growth while browsing large libraries.
- Idle log polling backs off automatically, reducing wakeups while ShadowClip is quiet.
- MP4 finalization runs below normal process priority to reduce its impact on games and other foreground applications.

## Reliability carried forward

- Includes the restored event toasts and replay/recording status indicators.
- Includes exact Explorer file selection for Home and Gallery `Show` actions.
- Includes the compact notification banners and more transparent persistent status icons.
