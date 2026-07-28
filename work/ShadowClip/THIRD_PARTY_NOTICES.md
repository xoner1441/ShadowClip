# Third-party notices

ShadowClip bundles third-party runtime tools for the release build. These tools remain owned by their respective projects and are distributed under their own licenses.

## OBS Studio

- Bundled component: OBS Studio portable runtime
- Tested bundled version: OBS Studio 32.1.2
- Project: https://obsproject.com/
- Source code: https://github.com/obsproject/obs-studio
- License notice included in the installed app folder: `tools\obs\data\obs-studio\license\gplv2.txt`

ShadowClip starts OBS locally through obs-websocket and uses OBS Game Capture for the optional `obs` backend. OBS is not modified by ShadowClip.

## FFmpeg

- Bundled component: FFmpeg essentials build from gyan.dev
- Tested bundled version: FFmpeg 8.1.1 essentials build
- Project: https://ffmpeg.org/
- Build provider: https://www.gyan.dev/ffmpeg/builds/
- License notice included in the installed app folder: `tools\ffmpeg\LICENSE`
- Additional bundled readme: `tools\ffmpeg\README.txt`

The bundled FFmpeg build reports `--enable-gpl --enable-version3` in its build configuration. ShadowClip calls FFmpeg as a separate executable for non-OBS capture paths, probing, trimming, muxing, and audio mixing.

## Notes for redistribution

If you publish ShadowClip installers publicly, keep these notice files and the bundled license files in the installer. For GPL-covered components, also provide a clear source-code link or written source offer matching the component license requirements.
