# ShadowClip 0.1.21-rc9

Closed-test hotfix release for the OBS replay startup watchdog.

## Changes since 0.1.21-rc8

- Fixed an OBS source-switch logging crash when the current foreground context is the desktop and no window context exists.
- `StartReplayBuffer` now waits until OBS reports the replay buffer as active before ShadowClip treats the start as successful.
- Added a short watchdog grace window after OBS replay restarts, preventing the watchdog from double-restarting its own canvas-resolution update.
- Canvas mismatch updates now skip the rest of the current watchdog tick after a successful OBS restart.

## Test focus

- Start replay after switching between `1440x1080` and `1920x1080`.
- Confirm the old `OBS capture source switch failed: 'NoneType' object has no attribute 'get'` message is gone.
- Confirm the OBS replay watchdog does not repeatedly restart immediately after `OBS canvas updated`.
