param(
    [string]$Version = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not $Version) {
    $versionMatch = Select-String -LiteralPath (Join-Path $projectRoot 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"'
    if (-not $versionMatch) {
        throw 'Unable to read project version from pyproject.toml.'
    }
    $Version = $versionMatch.Matches[0].Groups[1].Value
}

$latestBuildFile = Join-Path $projectRoot 'build\latest-python-app.txt'
if (-not (Test-Path -LiteralPath $latestBuildFile)) {
    throw 'No packaged application found. Run scripts\build_python.ps1 first.'
}
$sourceDir = (Get-Content -LiteralPath $latestBuildFile -Raw).Trim()
if (-not (Test-Path -LiteralPath (Join-Path $sourceDir 'PhoebeCleanerQt.exe'))) {
    throw "Packaged executable not found in $sourceDir"
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $iscc) {
    throw 'Inno Setup 6 was not found. Install JRSoftware.InnoSetup first.'
}

$releaseDir = Join-Path $projectRoot 'release'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
$iss = Join-Path $projectRoot 'installer\phoebe-cleaner.iss'
& $iscc "/DAppVersion=$Version" "/DSourceDir=$sourceDir" "/DOutputDir=$releaseDir" $iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$installer = Join-Path $releaseDir "PhoebeCleaner-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Expected installer was not created: $installer"
}
$hash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
Write-Host "Installer: $installer"
Write-Host "Size: $([math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 2)) MiB"
Write-Host "SHA256: $($hash.Hash)"
