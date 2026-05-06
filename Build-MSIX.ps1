<#
.SYNOPSIS
    Build script for Zava Insurance MSIX package for Microsoft Store.

.DESCRIPTION
    1. Generates icon assets
    2. Builds PyInstaller exe bundle
    3. Packages into MSIX using makeappx
    4. Optionally signs for local testing

.NOTES
    Run from the Insurance-NPU-Prototype directory.
    Requires: Python 3.12+, PyInstaller, pywebview, Pillow, Windows SDK
#>

param(
    [switch]$SkipBuild,
    [switch]$SignLocal
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }

$makeappx = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\arm64\makeappx.exe"
$signtool = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\arm64\signtool.exe"
$outputDir = Join-Path $root "dist"
$msixOutput = Join-Path $root "dist\ZavaInsurance.msix"
$pyinstallerDist = Join-Path $root "dist\ZavaInsurance"
$packagingDir = Join-Path $root "packaging"

Write-Host "=== Zava Insurance MSIX Build ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Generate icon assets
Write-Host "[1/4] Generating icon assets..." -ForegroundColor Yellow
Push-Location $root
python generate_assets.py
if ($LASTEXITCODE -ne 0) { throw "Asset generation failed" }
Pop-Location
Write-Host "  Done." -ForegroundColor Green

# Step 1b: Generate ICO file for PyInstaller
Write-Host "  Creating .ico file..." -ForegroundColor Yellow
python -c @"
from PIL import Image
import os
icon_sizes = [(16,16),(32,32),(48,48),(256,256)]
imgs = []
for s in icon_sizes:
    img = Image.open(os.path.join('packaging','Assets','Square44x44Logo.png')).resize(s, Image.LANCZOS)
    imgs.append(img)
imgs[0].save(os.path.join('packaging','Assets','app.ico'), format='ICO', sizes=[(i.width,i.height) for i in imgs], append_images=imgs[1:])
print('  Created app.ico')
"@

# Step 2: PyInstaller build
if (-not $SkipBuild) {
    Write-Host "[2/4] Building with PyInstaller (this may take a few minutes)..." -ForegroundColor Yellow
    Push-Location $root

    # Clean previous build
    if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

    pyinstaller ZavaInsurance.spec --noconfirm 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    Pop-Location
    Write-Host "  Build complete." -ForegroundColor Green
} else {
    Write-Host "[2/4] Skipping build (--SkipBuild)." -ForegroundColor DarkYellow
}

# Step 3: Assemble MSIX layout
Write-Host "[3/4] Assembling MSIX package layout..." -ForegroundColor Yellow

$msixLayout = Join-Path $root "dist\msix_layout"
if (Test-Path $msixLayout) { Remove-Item $msixLayout -Recurse -Force }
New-Item -ItemType Directory -Path $msixLayout -Force | Out-Null

# Copy PyInstaller output
Copy-Item "$pyinstallerDist\*" $msixLayout -Recurse

# Copy manifest
Copy-Item (Join-Path $packagingDir "AppxManifest.xml") $msixLayout

# Copy assets
$assetsTarget = Join-Path $msixLayout "Assets"
New-Item -ItemType Directory -Path $assetsTarget -Force | Out-Null
Copy-Item (Join-Path $packagingDir "Assets\*.png") $assetsTarget

Write-Host "  Layout ready at: $msixLayout" -ForegroundColor Green

# Step 4: Create MSIX package
Write-Host "[4/4] Creating MSIX package..." -ForegroundColor Yellow

if (Test-Path $msixOutput) { Remove-Item $msixOutput -Force }

& $makeappx pack /d $msixLayout /p $msixOutput /o
if ($LASTEXITCODE -ne 0) { throw "makeappx pack failed" }

Write-Host "  Package created: $msixOutput" -ForegroundColor Green

# Optional: Sign for local testing
if ($SignLocal) {
    Write-Host ""
    Write-Host "[Optional] Signing for local testing..." -ForegroundColor Yellow

    $certFile = Join-Path $root "dist\test_cert.pfx"

    # Create self-signed cert matching publisher
    $cert = New-SelfSignedCertificate `
        -Type Custom `
        -Subject "CN=7700A290-CE8F-4D64-A739-7B7088998B5E" `
        -KeyUsage DigitalSignature `
        -FriendlyName "Zava Insurance Test" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")

    # Export cert
    $pwd = ConvertTo-SecureString -String "ZavaTest123!" -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $certFile -Password $pwd | Out-Null

    # Sign
    & $signtool sign /fd SHA256 /a /f $certFile /p "ZavaTest123!" $msixOutput
    if ($LASTEXITCODE -ne 0) { Write-Host "  Signing failed (non-fatal for Store submission)" -ForegroundColor DarkYellow }
    else { Write-Host "  Signed for local testing." -ForegroundColor Green }
}

Write-Host ""
Write-Host "=== BUILD COMPLETE ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Output: $msixOutput" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Test locally:  Add-AppPackage -Path '$msixOutput'" -ForegroundColor White
Write-Host "  2. Upload to Partner Center: https://partner.microsoft.com/dashboard" -ForegroundColor White
Write-Host "     -> Apps and Games -> Zava Insurance -> Packages -> Upload" -ForegroundColor DarkGray
Write-Host ""
