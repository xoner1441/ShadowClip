# ShadowClip 0.1.21-rc29

- Added height-aware scrolling to the Home dashboard so Recent Logs and lower panels remain reachable in smaller windows.
- Applied the same shared module scroller to Capture, Video, Audio, HUD, Hotkeys, Storage, and Updates.
- Scrollbars are hidden while all content fits and appear automatically as soon as the module overflows vertically.
- Mouse-wheel scrolling works anywhere over a module, including nested cards, previews, labels, and controls.
- Returning to a sufficiently large window hides the scrollbar and resets the module to its top position.
- Kept Clips and Logs on their dedicated internal scroll views to avoid nested scroll conflicts.
