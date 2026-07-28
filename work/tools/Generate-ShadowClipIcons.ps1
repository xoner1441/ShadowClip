param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $OutputDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $OutputDir = Join-Path $scriptDir "..\ShadowClip\assets\icons"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Add-Type -AssemblyName System.Drawing

$sizes = @(18, 20, 24, 34, 46, 48)
$colors = @{
    accent = "#80d51a"
    light  = "#d7dee9"
    dark   = "#071007"
}
$icons = @(
    "home", "clips", "capture", "video", "audio", "hud", "storage", "updates", "logs", "settings",
    "replay", "record", "encoder", "timer", "audio_bars", "image", "folder", "clapper", "trash", "open", "check"
)

function Convert-HexColor {
    param([string]$Hex)
    $value = $Hex.TrimStart("#")
    return [System.Drawing.Color]::FromArgb(
        255,
        [Convert]::ToInt32($value.Substring(0, 2), 16),
        [Convert]::ToInt32($value.Substring(2, 2), 16),
        [Convert]::ToInt32($value.Substring(4, 2), 16)
    )
}

function New-PointArray {
    param([double[]]$Values)
    $points = New-Object System.Drawing.PointF[] ($Values.Count / 2)
    for ($i = 0; $i -lt $Values.Count; $i += 2) {
        $points[$i / 2] = New-Object System.Drawing.PointF ([single]$Values[$i]), ([single]$Values[$i + 1])
    }
    return $points
}

function Draw-Icon {
    param(
        [System.Drawing.Graphics]$Graphics,
        [string]$Key,
        [int]$Size,
        [System.Drawing.Color]$Color
    )

    $Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $Graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $Graphics.ScaleTransform($Size / 48.0, $Size / 48.0)

    $pen = New-Object System.Drawing.Pen $Color, 2.8
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $brush = New-Object System.Drawing.SolidBrush $Color

    function Line([double[]]$Values) {
        $points = New-PointArray $Values
        if ($points.Count -eq 2) {
            $Graphics.DrawLine($pen, $points[0], $points[1])
        }
        elseif ($points.Count -gt 2) {
            $Graphics.DrawLines($pen, $points)
        }
    }
    function Rect([double]$X1, [double]$Y1, [double]$X2, [double]$Y2) {
        $Graphics.DrawRectangle($pen, [single]$X1, [single]$Y1, [single]($X2 - $X1), [single]($Y2 - $Y1))
    }
    function Oval([double]$X1, [double]$Y1, [double]$X2, [double]$Y2, [switch]$Fill) {
        if ($Fill) {
            $Graphics.FillEllipse($brush, [single]$X1, [single]$Y1, [single]($X2 - $X1), [single]($Y2 - $Y1))
        }
        else {
            $Graphics.DrawEllipse($pen, [single]$X1, [single]$Y1, [single]($X2 - $X1), [single]($Y2 - $Y1))
        }
    }
    function Arc([double]$X1, [double]$Y1, [double]$X2, [double]$Y2, [double]$Start, [double]$Sweep) {
        $Graphics.DrawArc($pen, [single]$X1, [single]$Y1, [single]($X2 - $X1), [single]($Y2 - $Y1), [single]$Start, [single]$Sweep)
    }
    function Poly([double[]]$Values, [switch]$Fill) {
        $points = New-PointArray $Values
        if ($Fill) {
            $Graphics.FillPolygon($brush, $points)
        }
        $Graphics.DrawPolygon($pen, $points)
    }

    switch ($Key) {
        "home" {
            Line @(10, 23, 24, 12, 38, 23)
            Line @(15, 22, 15, 37, 33, 37, 33, 22)
            Line @(21, 37, 21, 29, 27, 29, 27, 37)
        }
        "clips" {
            Rect 11 13 37 35
            Poly @(21, 19, 21, 29, 30, 24) -Fill
        }
        "capture" {
            Oval 22 22 26 26 -Fill
            Line @(24, 8, 24, 17)
            Line @(24, 31, 24, 40)
            Line @(8, 24, 17, 24)
            Line @(31, 24, 40, 24)
            Line @(20, 12, 24, 8, 28, 12)
            Line @(20, 36, 24, 40, 28, 36)
            Line @(12, 20, 8, 24, 12, 28)
            Line @(36, 20, 40, 24, 36, 28)
        }
        "video" {
            Rect 12 10 36 38
            Line @(18, 10, 18, 38)
            Line @(30, 10, 30, 38)
            foreach ($y in @(15, 24, 33)) {
                Line @(13, $y, 16, $y)
                Line @(32, $y, 35, $y)
            }
        }
        "audio" {
            Line @(10, 20, 16, 20, 25, 13, 25, 35, 16, 28, 10, 28, 10, 20)
            Arc 25 18 36 30 -45 90
            Arc 26 12 43 36 -45 90
        }
        "hud" {
            Line @(11, 18, 11, 11, 18, 11)
            Line @(30, 11, 37, 11, 37, 18)
            Line @(37, 30, 37, 37, 30, 37)
            Line @(18, 37, 11, 37, 11, 30)
            Rect 18 18 30 30
        }
        "storage" {
            Arc 12 9 36 21 0 360
            Line @(12, 15, 12, 34)
            Line @(36, 15, 36, 34)
            Arc 12 28 36 40 180 180
            Arc 12 18 36 30 180 180
        }
        "updates" {
            Line @(15, 33, 33, 33)
            Arc 10 18 25 34 95 175
            Arc 19 12 34 28 30 220
            Arc 28 18 41 34 -20 135
            Line @(24, 34, 24, 18)
            Line @(18, 24, 24, 18, 30, 24)
        }
        "logs" {
            Rect 12 10 36 38
            foreach ($y in @(17, 24, 31)) {
                Line @(18, $y, 32, $y)
                Oval 14 ($y - 1.5) 16 ($y + 1.5) -Fill
            }
        }
        "settings" {
            Oval 18 18 30 30
            foreach ($line in @(
                @(24, 8, 24, 14), @(24, 34, 24, 40), @(8, 24, 14, 24), @(34, 24, 40, 24),
                @(13, 13, 17, 17), @(31, 31, 35, 35), @(35, 13, 31, 17), @(17, 31, 13, 35)
            )) {
                Line $line
            }
        }
        "replay" {
            Arc 10 10 38 38 35 285
            Line @(37, 17, 37, 28, 27, 27)
        }
        "record" {
            Oval 13 13 35 35
            Oval 20 20 28 28 -Fill
        }
        "encoder" {
            Rect 15 15 33 33
            Oval 21 21 27 27 -Fill
            foreach ($v in @(18, 24, 30)) {
                Line @($v, 10, $v, 15)
                Line @($v, 33, $v, 38)
                Line @(10, $v, 15, $v)
                Line @(33, $v, 38, $v)
            }
        }
        "timer" {
            Oval 12 14 36 38
            Line @(20, 9, 28, 9)
            Line @(24, 9, 24, 14)
            Line @(24, 24, 24, 17)
            Line @(24, 24, 30, 28)
            Line @(34, 13, 38, 17)
        }
        "audio_bars" {
            $oldWidth = $pen.Width
            $pen.Width = 3.6
            foreach ($line in @(
                @(12, 22, 12, 28), @(18, 16, 18, 34), @(24, 10, 24, 40), @(30, 16, 30, 34), @(36, 22, 36, 28)
            )) {
                Line $line
            }
            $pen.Width = $oldWidth
        }
        "image" {
            Rect 11 12 37 36
            Oval 28 17 32 21 -Fill
            Line @(15, 32, 22, 24, 28, 30, 32, 26, 37, 32)
        }
        "folder" {
            Line @(9, 17, 20, 17, 23, 21, 39, 21, 39, 36, 9, 36, 9, 17)
        }
        "clapper" {
            Rect 13 18 35 35
            Line @(13, 18, 35, 18)
            Line @(17, 18, 22, 12)
            Line @(25, 18, 30, 12)
            Line @(13, 18, 17, 12, 35, 12)
        }
        "trash" {
            Line @(16, 17, 32, 17)
            Line @(20, 13, 28, 13)
            Rect 18 19 30 36
            Line @(22, 23, 22, 32)
            Line @(26, 23, 26, 32)
        }
        "open" {
            Rect 13 17 31 35
            Line @(25, 13, 35, 13, 35, 23)
            Line @(23, 25, 35, 13)
        }
        "check" {
            $oldWidth = $pen.Width
            $pen.Width = 4.2
            Line @(14, 25, 21, 32, 35, 16)
            $pen.Width = $oldWidth
        }
        default {}
    }

    $pen.Dispose()
    $brush.Dispose()
}

foreach ($size in $sizes) {
    foreach ($variant in $colors.Keys) {
        $color = Convert-HexColor $colors[$variant]
        foreach ($icon in $icons) {
            $bitmap = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $graphics.Clear([System.Drawing.Color]::Transparent)
            Draw-Icon -Graphics $graphics -Key $icon -Size $size -Color $color
            $path = Join-Path $OutputDir "$($icon)_$($size)_$variant.png"
            $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }
}

Write-Host "Generated ShadowClip icons in $OutputDir"
