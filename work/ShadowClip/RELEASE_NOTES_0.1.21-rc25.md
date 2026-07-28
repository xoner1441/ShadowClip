# ShadowClip 0.1.21-rc25

- Added a one-click Capture test to the Updates page.
- The test records a fresh ten-second replay clip while guiding the user to show motion, play desktop audio, and speak into the microphone.
- Added validation for file size, video stream, clip duration, resolution, average FPS, black-screen ratio, audio stream, audio/video start timing, and detected silence.
- Added a scrollable in-app result report with targeted troubleshooting suggestions and direct Open clip / Show in folder actions.
- Capture tests are stored as replay media below the `ShadowClip Tests` folder for easy inspection.
- The test temporarily resets replay history, restores all normal capture settings afterward, and restarts Instant Replay only when it was running before the test.
- Added the latest capture-test result to exported diagnostics.
