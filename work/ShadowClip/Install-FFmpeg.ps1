param(
    [string]$Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir = Join-Path $AppDir "tools"
$InstallDir = Join-Path $ToolsDir "ffmpeg"
$TempDir = Join-Path $ToolsDir "_ffmpeg_download"
$ZipPath = Join-Path $ToolsDir "ffmpeg.zip"

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

$resolvedTools = [System.IO.Path]::GetFullPath($ToolsDir)
$resolvedTemp = [System.IO.Path]::GetFullPath($TempDir)
$resolvedInstall = [System.IO.Path]::GetFullPath($InstallDir)
if (-not $resolvedTemp.StartsWith($resolvedTools, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Safety check failed for temp directory: $resolvedTemp"
}
if (-not $resolvedInstall.StartsWith($resolvedTools, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Safety check failed for install directory: $resolvedInstall"
}

if (Test-Path -LiteralPath $TempDir) {
    Remove-Item -LiteralPath $TempDir -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Write-Host "Downloading FFmpeg..."
Invoke-WebRequest -Uri $Url -OutFile $ZipPath

Write-Host "Extracting FFmpeg..."
Expand-Archive -LiteralPath $ZipPath -DestinationPath $TempDir -Force

$ffmpegExe = Get-ChildItem -LiteralPath $TempDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    throw "ffmpeg.exe was not found in the archive."
}

$sourceRoot = Split-Path -Parent (Split-Path -Parent $ffmpegExe.FullName)
if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
Copy-Item -LiteralPath $sourceRoot -Destination $InstallDir -Recurse

Remove-Item -LiteralPath $TempDir -Recurse -Force
Remove-Item -LiteralPath $ZipPath -Force

$configPath = Join-Path $AppDir "shadowclip.config.json"
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
} else {
    $config = [pscustomobject]@{}
}
$config | Add-Member -NotePropertyName "ffmpeg_path" -NotePropertyValue (Join-Path $InstallDir "bin\ffmpeg.exe") -Force
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8

Write-Host "FFmpeg installed:"
Write-Host (Join-Path $InstallDir "bin\ffmpeg.exe")
