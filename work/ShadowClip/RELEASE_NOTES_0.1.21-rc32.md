# ShadowClip 0.1.21-rc32

- Fixed an OBS 32.1.2 cold-start crash in `OBSBasicStats::Update` / `obs_get_video` that could occur seconds after Windows login.
- Added an eight-second cold-start guard before ShadowClip changes OBS video, profile, scene, or replay settings.
- Require two consecutive valid video and scene readiness samples before OBS configuration begins.
- Serialize OBS runtime startup so replay, recording, and watchdog requests cannot initialize the private OBS instance concurrently.
- Restart the private OBS runtime once when it fails before frontend/video readiness, allowing startup to recover without manual intervention.
- Kept the Minecraft `win-capture.dll` safeguards introduced in rc31.
