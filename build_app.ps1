param(
    [string]$AppName
)

$ErrorActionPreference = "Stop"
$BuildTimestamp = Get-Date -Format "yyyyMMddHHmm"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($AppName)) {
    $ProductName = "BLE$([char]0x4EA7)$([char]0x54C1)$([char]0x4EA7)$([char]0x6D4B)$([char]0x6A21)$([char]0x62DF)$([char]0x5668)"
    $AppName = "$ProductName-V1-$BuildTimestamp"
}

$PyInstallerCandidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"),
    (Join-Path $env:USERPROFILE "Desktop\factory-gui-test\.venv\Scripts\pyinstaller.exe")
)
$PyInstaller = $PyInstallerCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($PyInstaller)) {
    throw "PyInstaller was not found. Install requirements.txt and pyinstaller in .venv."
}

$EntryPath = Join-Path $ProjectRoot "app.py"
$IconPath = Join-Path $ProjectRoot "assets\linp.ico"
$ProductsPath = Join-Path $ProjectRoot "products.json"
foreach ($RequiredPath in @($EntryPath, $IconPath, $ProductsPath)) {
    if (!(Test-Path $RequiredPath)) {
        throw "Missing package input: $RequiredPath"
    }
}

Push-Location $ProjectRoot
try {
    & $PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --windowed `
        --icon $IconPath `
        --add-data "$ProductsPath;." `
        --add-data "assets;assets" `
        --name $AppName `
        $EntryPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$ExePath = Join-Path $ProjectRoot "dist\$AppName.exe"
Write-Host "Package created: $ExePath"
