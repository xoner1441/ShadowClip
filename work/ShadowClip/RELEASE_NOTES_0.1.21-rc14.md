# ShadowClip 0.1.21-rc14

- Hardened the in-app updater flow to avoid first-start PyInstaller `_MEI` runtime extraction errors after installing an update.
- Update installs now stop replay/recording first, close ShadowClip, run the installer silently, wait for it to finish, then relaunch after a short delay.
- In-app update installs now pass `/NORESTARTAPPLICATIONS` so Windows/Inno Setup does not try to restart ShadowClip before the installer is fully settled.
