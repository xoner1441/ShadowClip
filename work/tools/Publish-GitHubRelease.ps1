param(
    [string]$Repository = "xoner1441/ShadowClip",
    [string]$Version = "0.1.23-rc11",
    [string]$AssetPath,
    [string]$ReleaseNotesPath,
    [switch]$Draft,
    [switch]$Prerelease
)

$ErrorActionPreference = "Stop"

function ConvertFrom-SecureStringToPlainText {
    param([securestring]$SecureString)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Invoke-GitHubJson {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [object]$Body = $null
    )

    $params = @{
        Method      = $Method
        Uri         = $Uri
        Headers     = $Headers
        ContentType = "application/json"
    }
    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 10)
    }
    Invoke-RestMethod @params
}

function Invoke-GitHubRaw {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [string]$Path
    )

    Add-Type -AssemblyName System.Net.Http
    $client = [Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $stream = $null
    $content = $null
    $request = $null
    $response = $null
    try {
        foreach ($entry in $Headers.GetEnumerator()) {
            [void]$client.DefaultRequestHeaders.TryAddWithoutValidation(
                [string]$entry.Key,
                [string]$entry.Value
            )
        }
        $stream = [IO.File]::OpenRead($Path)
        $content = [Net.Http.StreamContent]::new($stream, 1024 * 1024)
        $content.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::new(
            "application/octet-stream"
        )
        $request = [Net.Http.HttpRequestMessage]::new(
            [Net.Http.HttpMethod]::new($Method),
            $Uri
        )
        $request.Content = $content
        $response = $client.SendAsync(
            $request,
            [Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "GitHub asset upload failed: HTTP $([int]$response.StatusCode) $responseBody"
        }
        if ($responseBody) {
            return $responseBody | ConvertFrom-Json
        }
    }
    finally {
        if ($response) {
            $response.Dispose()
        }
        if ($request) {
            $request.Dispose()
        }
        elseif ($content) {
            $content.Dispose()
        }
        elseif ($stream) {
            $stream.Dispose()
        }
        $client.Dispose()
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path -LiteralPath (Join-Path $scriptDir "..\..")

if (-not $AssetPath) {
    $AssetPath = Join-Path $repoRoot "outputs\installer\ShadowClipSetup-$Version.exe"
}
if (-not $ReleaseNotesPath) {
    $ReleaseNotesPath = Join-Path $repoRoot "work\ShadowClip\RELEASE_NOTES_$Version.md"
}

$asset = Resolve-Path -LiteralPath $AssetPath
$notes = Resolve-Path -LiteralPath $ReleaseNotesPath
$assetName = Split-Path -Leaf $asset.Path
$tagName = "v$Version"
$releaseName = "ShadowClip $Version"
$releaseBody = [IO.File]::ReadAllText($notes.Path, [Text.Encoding]::UTF8)

$token = $env:GITHUB_TOKEN
if (-not $token) {
    $secureToken = Read-Host "GitHub token with Contents: Read/Write permission" -AsSecureString
    $token = ConvertFrom-SecureStringToPlainText $secureToken
}
if (-not $token) {
    throw "No GitHub token provided."
}

$headers = @{
    Accept                 = "application/vnd.github+json"
    Authorization          = "Bearer $token"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "ShadowClip-release-publisher"
}

$apiBase = "https://api.github.com/repos/$Repository"
$release = $null
try {
    $release = Invoke-GitHubJson -Method Get -Uri "$apiBase/releases/tags/$tagName" -Headers $headers
    Write-Host "Found existing release: $tagName"
}
catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -ne 404) {
        throw
    }
}

if (-not $release) {
    $release = Invoke-GitHubJson -Method Post -Uri "$apiBase/releases" -Headers $headers -Body @{
        tag_name         = $tagName
        target_commitish = "main"
        name             = $releaseName
        body             = $releaseBody
        draft            = [bool]$Draft
        prerelease       = [bool]$Prerelease
    }
    Write-Host "Created release: $tagName"
}
else {
    $release = Invoke-GitHubJson -Method Patch -Uri "$apiBase/releases/$($release.id)" -Headers $headers -Body @{
        name       = $releaseName
        body       = $releaseBody
        draft      = [bool]$Draft
        prerelease = [bool]$Prerelease
    }
    Write-Host "Updated release metadata: $tagName"
}

$assets = Invoke-GitHubJson -Method Get -Uri "$apiBase/releases/$($release.id)/assets?per_page=100" -Headers $headers
foreach ($existing in $assets) {
    if ($existing.name -eq $assetName -or $existing.name -eq "$assetName.sha256") {
        Invoke-GitHubJson -Method Delete -Uri "$apiBase/releases/assets/$($existing.id)" -Headers $headers | Out-Null
        Write-Host "Deleted old asset: $($existing.name)"
    }
}

$uploadBase = ($release.upload_url -replace "\{\?name,label\}$", "")
$uploadUri = "${uploadBase}?name=$([uri]::EscapeDataString($assetName))"
Invoke-GitHubRaw -Method Post -Uri $uploadUri -Headers $headers -Path $asset.Path | Out-Null
Write-Host "Uploaded asset: $assetName"

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset.Path).Hash
$shaPath = Join-Path ([IO.Path]::GetTempPath()) "$assetName.sha256"
"$hash  $assetName" | Set-Content -LiteralPath $shaPath -Encoding ASCII
$shaUploadUri = "${uploadBase}?name=$([uri]::EscapeDataString("$assetName.sha256"))"
Invoke-GitHubRaw -Method Post -Uri $shaUploadUri -Headers $headers -Path $shaPath | Out-Null
Write-Host "Uploaded asset: $assetName.sha256"

Write-Host ""
Write-Host "Release URL: $($release.html_url)"
Write-Host "SHA256: $hash"
