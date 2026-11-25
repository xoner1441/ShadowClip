# ShadowClip 0.1.23-rc17

## Lower GPU usage

- Display capture now uses DXGI desktop duplication instead of Windows Graphics Capture when no game is being captured, which removes most idle GPU load.
- New "Output resolution" setting (Native, 1440p, 1080p, 900p, 720p) downscales the OBS output to reduce encoder load.
- OBS recording now uses Advanced output with a lighter NVENC preset (P4) and falls back to Simple output automatically if Advanced output cannot start.

## Smoother saving

- Saving a long recording no longer freezes the PC for several seconds: the seek-finalization remux now runs with very low I/O and memory priority.

## Better automatic bitrate

- The automatic bitrate scales more gently with frame rate. At 1080p and 120 FPS the High preset now targets about 53 Mbps instead of 70 Mbps.

## Clip gallery

- Cards now fill the full gallery width; a leftover empty column after startup is gone.
- Preview thumbnails are generated in 16:9 at the card width, so they are no longer cropped.

## Window resizing

- Resizing the ShadowClip window is now smooth: Windows no longer repaints every widget on each resize step, and the layout follows the window edge at a limited rate.
- Hidden pages are no longer re-laid out while resizing, and the Home and gallery previews only update once resizing settles.
