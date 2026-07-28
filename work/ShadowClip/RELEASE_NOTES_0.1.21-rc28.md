# ShadowClip 0.1.21-rc28

- Added `Capture desktop overlays (WGC)` to the main Capture page and the HUD capture settings.
- Overlay capture records the Windows desktop composition above the game source for Xbox Game Bar, Crosshair X, and other visible desktop overlays.
- Enabling overlay capture automatically selects the OBS backend because FFmpeg game/desktop paths cannot provide the same compositing behavior.
- Game Capture remains active underneath the WGC desktop layer as a safety source.
- Extended black-screen recovery with an overlay-specific path: a black WGC overlay layer is removed automatically and capture falls back to the underlying game source.
- Changing the overlay setting clears learned source strategies so the new source order takes effect immediately.
- Kept overlay capture disabled by default to preserve the established performance and compatibility behavior for existing installations.
