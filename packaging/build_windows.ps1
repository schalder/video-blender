$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Version = if ($env:VERSION) { $env:VERSION } else { "1.0.0" }
$Dist = Join-Path $Root "dist"
$Zip = Join-Path $Dist "Video-Blender-$Version-windows-x64.zip"

if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt pyinstaller

# Fetch Windows static ffmpeg/ffprobe
New-Item -ItemType Directory -Force -Path "packaging\bin" | Out-Null
$tag = "b6.0"
$base = "https://github.com/eugeneware/ffmpeg-static/releases/download/$tag"
Invoke-WebRequest -Uri "$base/ffmpeg-win32-x64" -OutFile "packaging\bin\ffmpeg.exe"
Invoke-WebRequest -Uri "$base/ffprobe-win32-x64" -OutFile "packaging\bin\ffprobe.exe"

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, "dist\Video Blender"
pyinstaller --noconfirm packaging\VideoBlender.spec

$AppDir = Join-Path $Dist "Video Blender"
if (-not (Test-Path $AppDir)) { throw "Missing $AppDir" }

@"
Video Blender $Version

1. Unzip this folder anywhere.
2. Run "Video Blender.exe".
3. Activate with your license key from:
   https://flagbattle.powerkits.net/dashboard.html#/video-blender
"@ | Set-Content -Path (Join-Path $AppDir "Read Me.txt")

if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path $AppDir -DestinationPath $Zip
Write-Host "Built: $Zip"
Get-Item $Zip | Format-List FullName, Length
