param(
    [string]$Version = "0.1.22",
    [string]$VersionNumeric = "0.1.22.0",
    [switch]$Force,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

function Assert-SafeBuildPath {
    param(
        [string]$Path,
        [string]$AllowedRoot
    )
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the build workspace: $fullPath"
    }
}

function Reset-BuildDirectory {
    param(
        [string]$Path,
        [string]$AllowedRoot
    )
    Assert-SafeBuildPath -Path $Path -AllowedRoot $AllowedRoot
    if (Test-Path -LiteralPath $Path) {
        if (-not $Force) {
            throw "Build path already exists. Re-run with -Force to replace it: $Path"
        }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-ObsRuntimePart {
    param(
        [string]$Source,
        [string]$Destination
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy.exe $Source $Destination /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XF *.pdb
    if ($LASTEXITCODE -ge 8) {
        throw "OBS runtime copy failed with robocopy exit code $LASTEXITCODE."
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..\..")).Path
$workRoot = Join-Path $repoRoot "work"
$sourceDir = Join-Path $workRoot "ShadowClip"
$sourcePath = Join-Path $sourceDir "ShadowClip.py"
$python = Join-Path $workRoot "shadowclip-build-venv\Scripts\python.exe"
$pyvenvConfig = Join-Path $workRoot "shadowclip-build-venv\pyvenv.cfg"
$hooksDir = Join-Path $workRoot "pyinstaller-hooks-tkfix"
$obsRuntime = Join-Path $workRoot "obs-runtime"
$buildDir = Join-Path $workRoot "pyinstaller-build-$Version"
$distDir = Join-Path $workRoot "pyinstaller-dist-$Version"
$specDir = Join-Path $workRoot "pyinstaller-spec-$Version"
$generatedDir = Join-Path $workRoot "release-generated-$Version"
$releaseDir = Join-Path $repoRoot "outputs\ShadowClipExeControlCenter_$Version"
$installerDir = Join-Path $repoRoot "outputs\installer"
$installerPath = Join-Path $installerDir "ShadowClipSetup-$Version.exe"

foreach ($path in @($sourcePath, $python, $pyvenvConfig, $hooksDir, $obsRuntime)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required build input was not found: $path"
    }
}

$sourceVersionMatch = Select-String -LiteralPath $sourcePath -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($sourceVersionMatch.Matches.Groups[1].Value -ne $Version) {
    throw "ShadowClip.py version does not match requested build version '$Version'."
}

$numericParts = @($VersionNumeric.Split(".") | ForEach-Object { [int]$_ })
if ($numericParts.Count -ne 4) {
    throw "VersionNumeric must contain four numeric parts, for example 0.1.22.0."
}

Reset-BuildDirectory -Path $buildDir -AllowedRoot $workRoot
Reset-BuildDirectory -Path $distDir -AllowedRoot $workRoot
Reset-BuildDirectory -Path $specDir -AllowedRoot $workRoot
Reset-BuildDirectory -Path $generatedDir -AllowedRoot $workRoot
Reset-BuildDirectory -Path $releaseDir -AllowedRoot (Join-Path $repoRoot "outputs")

$versionTuple = "($($numericParts -join ', '))"
$versionFile = Join-Path $generatedDir "ShadowClip.version.txt"
$versionText = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=$versionTuple,
    prodvers=$versionTuple,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'ShadowClip'),
          StringStruct('FileDescription', 'ShadowClip'),
          StringStruct('FileVersion', '$VersionNumeric'),
          StringStruct('InternalName', 'ShadowClip'),
          StringStruct('LegalCopyright', 'Copyright (c) 2026 ShadowClip'),
          StringStruct('OriginalFilename', 'ShadowClip.exe'),
          StringStruct('ProductName', 'ShadowClip'),
          StringStruct('ProductVersion', '$VersionNumeric')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
$versionText | Set-Content -LiteralPath $versionFile -Encoding UTF8

$pythonHomeLine = Get-Content -LiteralPath $pyvenvConfig |
    Where-Object { $_ -match '^\s*home\s*=' } |
    Select-Object -First 1
$pythonHome = ($pythonHomeLine -split '=', 2)[1].Trim()
if (-not (Test-Path -LiteralPath $pythonHome)) {
    throw "Base Python runtime was not found: $pythonHome"
}

$pyinstallerArguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--log-level", "WARN",
    "--onefile",
    "--windowed",
    "--name", "ShadowClip",
    "--distpath", $distDir,
    "--workpath", $buildDir,
    "--specpath", $specDir,
    "--icon", (Join-Path $sourceDir "ShadowClip.ico"),
    "--version-file", $versionFile,
    "--additional-hooks-dir", $hooksDir,
    "--hidden-import", "_tkinter",
    "--hidden-import", "tkinter",
    "--hidden-import", "tkinter.ttk",
    "--hidden-import", "tkinter.messagebox",
    "--hidden-import", "tkinter.simpledialog",
    "--add-binary", "$(Join-Path $pythonHome 'DLLs\_tkinter.pyd');.",
    "--add-binary", "$(Join-Path $pythonHome 'DLLs\tcl86t.dll');.",
    "--add-binary", "$(Join-Path $pythonHome 'DLLs\tk86t.dll');.",
    "--add-data", "$(Join-Path $pythonHome 'tcl\tcl8.6');_tcl_data",
    "--add-data", "$(Join-Path $pythonHome 'tcl\tk8.6');_tk_data",
    "--add-data", "$(Join-Path $sourceDir 'assets');assets",
    $sourcePath
)

& $python @pyinstallerArguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

$releaseNotesName = "RELEASE_NOTES_$Version.md"
$copyFiles = @(
    "ShadowClip.ico",
    "ShadowClip.py",
    "README.md",
    $releaseNotesName,
    "THIRD_PARTY_NOTICES.md",
    "Install-FFmpeg.ps1",
    "Start-ShadowClip.cmd"
)
Copy-Item -LiteralPath (Join-Path $distDir "ShadowClip.exe") -Destination $releaseDir
foreach ($item in $copyFiles) {
    Copy-Item -LiteralPath (Join-Path $sourceDir $item) -Destination $releaseDir
}
Copy-Item -LiteralPath (Join-Path $repoRoot "work\installer\shadowclip.installer.config.json") -Destination (Join-Path $releaseDir "shadowclip.config.json")
Copy-Item -LiteralPath (Join-Path $sourceDir "assets") -Destination $releaseDir -Recurse

$releaseTools = Join-Path $releaseDir "tools"
New-Item -ItemType Directory -Force -Path $releaseTools | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceDir "tools\ffmpeg") -Destination $releaseTools -Recurse
$releaseObs = Join-Path $releaseTools "obs"
foreach ($part in @("bin", "data", "obs-plugins")) {
    Copy-ObsRuntimePart -Source (Join-Path $obsRuntime $part) -Destination (Join-Path $releaseObs $part)
}

$testScript = Join-Path $scriptDir "Test-ShadowClipRelease.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $testScript `
    -Version $Version `
    -VersionNumeric $VersionNumeric `
    -ReleaseDir $releaseDir
if ($LASTEXITCODE -ne 0) {
    throw "Portable release validation failed."
}

if (-not $SkipInstaller) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "work\installer\Build-Installer.ps1") `
        -Version $Version `
        -VersionNumeric $VersionNumeric `
        -ReleaseDir $releaseDir `
        -OutputDir $installerDir
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build failed."
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $testScript `
        -Version $Version `
        -VersionNumeric $VersionNumeric `
        -ReleaseDir $releaseDir `
        -InstallerPath $installerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Final release validation failed."
    }
}

$hashLines = @()
$portableExe = Join-Path $releaseDir "ShadowClip.exe"
$hashLines += "$((Get-FileHash -Algorithm SHA256 -LiteralPath $portableExe).Hash)  ShadowClip.exe"
if (Test-Path -LiteralPath $installerPath) {
    $hashLines += "$((Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash)  $(Split-Path -Leaf $installerPath)"
}
$hashPath = Join-Path $repoRoot "outputs\ShadowClip-$Version-SHA256.txt"
$hashLines | Set-Content -LiteralPath $hashPath -Encoding ASCII

Write-Host ""
Write-Host "ShadowClip $Version release build completed."
Write-Host "Portable package: $releaseDir"
if (-not $SkipInstaller) {
    Write-Host "Installer: $installerPath"
}
Write-Host "Checksums: $hashPath"
