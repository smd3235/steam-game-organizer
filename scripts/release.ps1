# Release build script for Steam Game Organizer (Rust)
#
# Builds the release exe and bundles it with 7-Zip and assets into a
# distributable zip for GitHub Releases.
#
# Legal: 7-Zip (7z.exe) is LGPL-licensed. It must be distributed with its
# license (tools/7z-license.txt) alongside the executable.
#
# Usage: .\tools\release.ps1

$ErrorActionPreference = "Stop"
$root = Get-Location
$bundleName = "steam-game-organizer-release"
$bundlePath = Join-Path $root $bundleName
$exeName = "steam-game-organizer.exe"

Write-Host "=== Steam Game Organizer Release Build ===" -ForegroundColor Green

# 1. Build release
Write-Host "`n[1/5] Building release exe with cargo..." -ForegroundColor Cyan
cargo build --release
if ($LASTEXITCODE -ne 0) { Write-Error "cargo build failed"; exit 1 }

# 2. Verify inputs exist
Write-Host "`n[2/5] Verifying inputs..." -ForegroundColor Cyan
$exePath = Join-Path $root "target/release/$exeName"
if (!(Test-Path $exePath)) { Write-Error "Release exe not found at $exePath"; exit 1 }
if (!(Test-Path "tools/7z.exe")) { Write-Error "tools/7z.exe not found! Required for archive extraction."; exit 1 }
if (!(Test-Path "tools/7z-license.txt")) { Write-Error "tools/7z-license.txt not found! Required for LGPL compliance."; exit 1 }

# 3. Clean and create bundle directory
Write-Host "`n[3/5] Creating bundle directory..." -ForegroundColor Cyan
if (Test-Path $bundleName) { Remove-Item $bundleName -Recurse -Force }
New-Item -ItemType Directory -Path $bundleName -Force | Out-Null

# 4. Copy files into bundle
Write-Host "`n[4/5] Copying files into bundle..." -ForegroundColor Cyan
Copy-Item $exePath -Destination "$bundleName/" -Force

New-Item -ItemType Directory -Path "$bundleName/runtime" -Force | Out-Null
Copy-Item "tools/7z.exe" -Destination "$bundleName/runtime/" -Force
Copy-Item "tools/7z-license.txt" -Destination "$bundleName/runtime/" -Force

Copy-Item "assets" -Destination "$bundleName/" -Recurse -Force

foreach ($doc in @("AGENTS.md", "ARCHITECTURE.md", "README.md", "CHANGELOG.md", "LICENSE")) {
    if (Test-Path $doc) { Copy-Item $doc -Destination "$bundleName/" -Force }
}

# 5. Zip the bundle
Write-Host "`n[5/5] Creating release zip..." -ForegroundColor Cyan
if (Test-Path "$bundleName.zip") { Remove-Item "$bundleName.zip" -Force }
Compress-Archive -Path "$bundleName/*" -DestinationPath "$bundleName.zip" -Force

$zipSize = (Get-Item "$bundleName.zip").Length / 1MB
Write-Host "`n=== Release bundle complete ===" -ForegroundColor Green
Write-Host "Zip: $bundleName.zip ($("{0:N2}" -f $zipSize) MB)" -ForegroundColor Green
Write-Host "Contents:" -ForegroundColor Gray
Get-ChildItem $bundleName -Recurse | Select-Object Name | Format-Table -AutoSize | Out-String | Write-Host

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Create a GitHub Release at https://github.com/smd3235/steam-game-organizer/releases/new"
Write-Host "  2. Upload $bundleName.zip as a release asset"
Write-Host "  3. Tag the release and add changelog notes"
Write-Host "  4. Publish the release"
