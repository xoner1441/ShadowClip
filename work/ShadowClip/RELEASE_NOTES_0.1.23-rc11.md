# ShadowClip 0.1.23-rc11

## Clearer capture feedback

- Temporary notifications are now compact text banners with an icon, accent bar, title, and supporting detail.
- Replay start and stop messages now read `Instant Replay started` and `Instant Replay stopped`.
- Persistent Replay and recording status remain icon-only so they no longer look like temporary notifications.
- The dark background behind persistent bottom-right status icons is more transparent while the colored icon remains easy to recognize.

## Reliability carried forward

- Includes the `Show` file-selection correction and fallback to the media file's actual parent folder.
- Includes the Tk window mapping fix for toasts and persistent capture-status icons.
- UI regression coverage verifies notification text, dimensions, visibility, and persistent-icon transparency.
