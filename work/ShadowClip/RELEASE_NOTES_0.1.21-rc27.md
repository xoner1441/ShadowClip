# ShadowClip 0.1.21-rc27

- Reworked OBS capture selection into a generic black-screen recovery pipeline instead of maintaining per-game exception lists.
- OBS Game Capture now runs above a live monitor-capture fallback, allowing transparent or unavailable game hooks to fall through to a visible desktop frame.
- Added lightweight final-scene validation through obs-websocket screenshots with a built-in PNG decoder and strict near-black thresholds.
- Automatically switches a failed capture from Game Capture to display capture, then from Automatic/DXGI to Windows Graphics Capture, and finally retries the exact foreground game window.
- Remembers the working capture strategy per application for the current ShadowClip session.
- Resets the replay window after a verified recovery so later clips do not contain previously detected black frames.
- Prevents a clip save while the current OBS scene is verified black and shows a user-facing recovery message instead of creating an unusable video.
- Added capture-recovery state to privacy-safe beta diagnostics.
- Serialized OBS WebSocket requests so the replay watchdog, recording watchdog, and clip-save thread cannot consume each other's responses.
