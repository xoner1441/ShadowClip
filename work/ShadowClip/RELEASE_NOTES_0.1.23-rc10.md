# ShadowClip 0.1.23-rc10

## Feedback visibility

- Fixed clip toasts remaining internally withdrawn after creation.
- Fixed Replay and recording status icons remaining internally withdrawn.
- Newly-created feedback windows are now mapped by Tk before the fullscreen-safe no-activate window style is applied.
- Toast creation errors are written to the ShadowClip log instead of disappearing silently.

## Show in folder

- Replaced the ambiguous Explorer command-line invocation with the Windows Shell API.
- File paths with spaces are passed as an explicitly quoted `/select` parameter.
- If Explorer cannot select a media file, ShadowClip opens that file's actual parent folder instead of the default Documents folder.

## Regression coverage

- Added a live Tk test that verifies toast and persistent capture-status windows leave the withdrawn state.
- Added exact-path and quoted-Explorer-parameter tests for gallery and Home `Show` actions.
