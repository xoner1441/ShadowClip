param(
    [string]$Version = "0.1.23-rc9",
    [string]$VersionNumeric = "0.1.23.9",
    [string]$ReleaseDir,
    [string]$InstallerPath,
    [string]$ReportPath
)

$ErrorActionPreference = "Stop"

function Assert-ReleaseCondition {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..\..")).Path
$sourceDir = Join-Path $repoRoot "work\ShadowClip"
$sourcePath = Join-Path $sourceDir "ShadowClip.py"
$testPath = Join-Path $repoRoot "work\tests\test_shadowclip_release.py"
$python = Join-Path $repoRoot "work\shadowclip-build-venv\Scripts\python.exe"

Assert-ReleaseCondition (Test-Path -LiteralPath $python) "Build Python was not found: $python"
Assert-ReleaseCondition (Test-Path -LiteralPath $sourcePath) "ShadowClip source was not found: $sourcePath"

& $python -m py_compile $sourcePath
Assert-ReleaseCondition ($LASTEXITCODE -eq 0) "Python compilation failed."
& $python $testPath
Assert-ReleaseCondition ($LASTEXITCODE -eq 0) "Release unit tests failed."

$sourceVersionMatch = Select-String -LiteralPath $sourcePath -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
$sourceVersion = $sourceVersionMatch.Matches.Groups[1].Value
Assert-ReleaseCondition ($sourceVersion -eq $Version) "Source version '$sourceVersion' does not match release version '$Version'."

$defaultConfigPath = Join-Path $repoRoot "work\installer\shadowclip.installer.config.json"
$defaultConfig = Get-Content -LiteralPath $defaultConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-ReleaseCondition (-not [bool]$defaultConfig.setup_completed) "Fresh-install config must not skip the setup wizard."
Assert-ReleaseCondition ([string]::IsNullOrWhiteSpace([string]$defaultConfig.beta_install_id)) "Fresh-install config contains a fixed beta install ID."
Assert-ReleaseCondition ([bool]$defaultConfig.check_updates_on_start) "Fresh-install update checks should be enabled."
Assert-ReleaseCondition ([bool]$defaultConfig.capture_desktop_overlays) "Fresh installs must enable desktop-overlay capture."
Assert-ReleaseCondition ([bool]$defaultConfig.capture_desktop_overlays_migrated) "Fresh-install overlay migration marker is missing."

$result = [ordered]@{
    version = $Version
    version_numeric = $VersionNumeric
    source_compile = "passed"
    unit_tests = "passed"
    default_config = "passed"
    release_package = "not_requested"
    installer = "not_requested"
    installer_signature = "not_checked"
    sha256 = ""
    checked_at = (Get-Date).ToString("o")
}

if ($ReleaseDir) {
    $ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).Path
    $required = @(
        "ShadowClip.exe",
        "ShadowClip.ico",
        "ShadowClip.py",
        "README.md",
        "RELEASE_NOTES_$Version.md",
        "THIRD_PARTY_NOTICES.md",
        "Install-FFmpeg.ps1",
        "Start-ShadowClip.cmd",
        "shadowclip.config.json",
        "assets\icons\home_34_accent.png",
        "assets\icons\replay_48_accent.png",
        "assets\sounds\pulse_deep_clip.wav",
        "assets\sounds\pulse_deep_start.wav",
        "assets\sounds\pulse_deep_stop.wav",
        "assets\sounds\pulse_deep_warning.wav",
        "tools\ffmpeg\bin\ffmpeg.exe",
        "tools\ffmpeg\bin\ffprobe.exe",
        "tools\ffmpeg\LICENSE",
        "tools\obs\bin\64bit\obs64.exe",
        "tools\obs\obs-plugins\64bit\obs-websocket.dll",
        "tools\obs\data\obs-studio\license\gplv2.txt"
    )
    foreach ($item in $required) {
        Assert-ReleaseCondition (Test-Path -LiteralPath (Join-Path $ReleaseDir $item)) "Release file is missing: $item"
    }

    $packagedSource = Join-Path $ReleaseDir "ShadowClip.py"
    $packagedVersionMatch = Select-String -LiteralPath $packagedSource -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    Assert-ReleaseCondition ($packagedVersionMatch.Matches.Groups[1].Value -eq $Version) "Packaged source has the wrong version."

    $portableConfig = Get-Content -LiteralPath (Join-Path $ReleaseDir "shadowclip.config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-ReleaseCondition (-not [bool]$portableConfig.setup_completed) "Portable config must open the setup wizard."
    Assert-ReleaseCondition ([string]::IsNullOrWhiteSpace([string]$portableConfig.beta_install_id)) "Portable config contains a fixed beta install ID."
    Assert-ReleaseCondition ([bool]$portableConfig.capture_desktop_overlays) "Portable config must enable desktop-overlay capture."
    Assert-ReleaseCondition ([bool]$portableConfig.capture_desktop_overlays_migrated) "Portable overlay migration marker is missing."

    $forbiddenFiles = @(
        Get-ChildItem -LiteralPath $ReleaseDir -File -Recurse -Filter "*.pdb"
        Get-ChildItem -LiteralPath $ReleaseDir -File -Recurse -Filter "*.pyc"
        Get-ChildItem -LiteralPath $ReleaseDir -File -Recurse |
            Where-Object { $_.FullName -match '\\(?:crashes|logs|__pycache__)\\' }
    )
    Assert-ReleaseCondition ($forbiddenFiles.Count -eq 0) "Release package contains build symbols, caches, or runtime logs."

    $exeInfo = (Get-Item -LiteralPath (Join-Path $ReleaseDir "ShadowClip.exe")).VersionInfo
    Assert-ReleaseCondition ($exeInfo.ProductVersion.Trim() -eq $VersionNumeric) "ShadowClip.exe ProductVersion is '$($exeInfo.ProductVersion)', expected '$VersionNumeric'."
    Assert-ReleaseCondition ($exeInfo.FileDescription -eq "ShadowClip") "ShadowClip.exe has no release file description."

    $ffmpegPath = Join-Path $ReleaseDir "tools\ffmpeg\bin\ffmpeg.exe"
    $ffmpegVersion = (& $ffmpegPath -version 2>&1 | Select-Object -First 1)
    Assert-ReleaseCondition ([string]$ffmpegVersion -match '^ffmpeg version') "Bundled FFmpeg did not return version information."
    $result.release_package = "passed"
}

if ($InstallerPath) {
    $InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
    $installerInfo = (Get-Item -LiteralPath $InstallerPath).VersionInfo
    Assert-ReleaseCondition ($installerInfo.ProductVersion.Trim() -eq $VersionNumeric) "Installer ProductVersion is '$($installerInfo.ProductVersion)', expected '$VersionNumeric'."
    $signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    $result.installer = "passed"
    $result.installer_signature = [string]$signature.Status
    $result.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash
}

if (-not $ReportPath) {
    $ReportPath = Join-Path $repoRoot "outputs\release-validation-$Version.json"
}
$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

Write-Host "ShadowClip release validation passed."
Write-Host "Report: $ReportPath"
if ($result.sha256) {
    Write-Host "Installer SHA256: $($result.sha256)"
}
