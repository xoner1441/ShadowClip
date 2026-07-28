# ShadowClip 0.1.21-rc16

- Hotkeys are now fully customizable without requiring Ctrl, Alt, Shift, or Win.
- Standalone keys such as F9, PrintScreen, Home, Numpad1, MediaPlayPause, or single letters can be assigned.
- Standalone hotkeys run through the low-level keyboard hook instead of being hard-reserved through Windows RegisterHotKey, so the key remains available to the foreground app.
- The Hotkeys page now captures key presses directly from each field for easier rebinding.
