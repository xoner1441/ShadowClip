param(
    [string]$Version = "0.1.23-rc10",
    [string]$VersionNumeric = "0.1.23.10",
    [string]$ReleaseDir,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path -LiteralPath (Join-Path $scriptDir "..\..")

if (-not $ReleaseDir) {
    $ReleaseDir = Join-Path $repoRoot "outputs\ShadowClipExeControlCenter_$Version"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot "outputs\installer"
}

$ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).Path
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

$releaseNotesName = "RELEASE_NOTES_$Version.md"
$required = @(
    "ShadowClip.exe",
    "ShadowClip.ico",
    "README.md",
    $releaseNotesName,
    "THIRD_PARTY_NOTICES.md",
    "Install-FFmpeg.ps1",
    "ShadowClip.py",
    "assets\icons\home_34_accent.png",
    "assets\icons\replay_48_accent.png",
    "assets\sounds\pulse_deep_clip.wav",
    "assets\sounds\pulse_deep_start.wav",
    "assets\sounds\pulse_deep_stop.wav",
    "assets\sounds\pulse_deep_warning.wav",
    "tools\ffmpeg\bin\ffmpeg.exe",
    "tools\ffmpeg\LICENSE",
    "tools\obs\bin\64bit\obs64.exe",
    "tools\obs\data\obs-studio\license\gplv2.txt"
)

foreach ($item in $required) {
    $path = Join-Path $ReleaseDir $item
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing release file: $path"
    }
}

$configPath = Join-Path $scriptDir "shadowclip.installer.config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Missing installer default config: $configPath"
}

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            $iscc = $candidate
            break
        }
    }
}

if (-not $iscc) {
    throw "Inno Setup compiler ISCC.exe was not found. Install Inno Setup 6, then rerun this script."
}

$issPath = Join-Path $scriptDir "ShadowClipInstaller.iss"
& $iscc `
    "/Qp" `
    "/DMyAppVersion=$Version" `
    "/DMyAppVersionNumeric=$VersionNumeric" `
    "/DSourceDir=$ReleaseDir" `
    "/DInstallerConfig=$configPath" `
    "/DReleaseNotesFile=$releaseNotesName" `
    "/DOutputDir=$OutputDir" `
    $issPath

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}

$setupPath = Join-Path $OutputDir "ShadowClipSetup-$Version.exe"
if (-not (Test-Path -LiteralPath $setupPath)) {
    throw "Installer build finished but setup was not found: $setupPath"
}

Write-Host "Built installer: $setupPath"
