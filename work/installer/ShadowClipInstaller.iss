#define MyAppName "ShadowClip"
#ifndef MyAppVersion
#define MyAppVersion "0.1.23-rc9"
#endif
#ifndef MyAppVersionNumeric
#define MyAppVersionNumeric "0.1.23.9"
#endif
#ifndef SourceDir
#define SourceDir "..\..\outputs\ShadowClipExeControlCenter_0.1.23-rc9"
#endif
#ifndef InstallerConfig
#define InstallerConfig "shadowclip.installer.config.json"
#endif
#ifndef ReleaseNotesFile
#define ReleaseNotesFile "RELEASE_NOTES_0.1.23-rc9.md"
#endif
#ifndef OutputDir
#define OutputDir "..\..\outputs\installer"
#endif

[Setup]
AppId={{D1D5F3B7-0EB4-4FA5-8F5D-2DA72161F1EF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ShadowClip
DefaultDirName={localappdata}\Programs\ShadowClip
DefaultGroupName=ShadowClip
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=ShadowClipSetup-{#MyAppVersion}
SetupIconFile={#SourceDir}\ShadowClip.ico
UninstallDisplayIcon={app}\ShadowClip.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartIfNeededByRun=no
VersionInfoVersion={#MyAppVersionNumeric}
VersionInfoCompany=ShadowClip
VersionInfoDescription=ShadowClip Setup
VersionInfoProductName=ShadowClip
VersionInfoProductVersion={#MyAppVersionNumeric}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Verknuepfungen:"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{userstartup}\ShadowClip.lnk"
Type: files; Name: "{userstartup}\ShadowClip.url"

[Files]
Source: "{#SourceDir}\ShadowClip.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\ShadowClip.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\{#ReleaseNotesFile}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\Install-FFmpeg.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\ShadowClip.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#InstallerConfig}"; DestDir: "{app}"; DestName: "shadowclip.config.json"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#SourceDir}\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ShadowClip"; Filename: "{app}\ShadowClip.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ShadowClip.ico"
Name: "{userdesktop}\ShadowClip"; Filename: "{app}\ShadowClip.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ShadowClip.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\ShadowClip.exe"; Description: "ShadowClip jetzt starten"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{userstartup}\ShadowClip.lnk"
Type: files; Name: "{userstartup}\ShadowClip.url"
