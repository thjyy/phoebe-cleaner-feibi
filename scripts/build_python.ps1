$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $projectRoot '.venv')
}

& $venvPython -m pip install --disable-pip-version-check -e $projectRoot pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed with exit code $LASTEXITCODE" }

$shellBuild = Join-Path $projectRoot 'build\shell'
& cmake -S $projectRoot -B $shellBuild -G Ninja -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE -ne 0) { throw "Shell bridge configuration failed with exit code $LASTEXITCODE" }
& cmake --build $shellBuild --target PhoebeShellExtension
if ($LASTEXITCODE -ne 0) { throw "Shell bridge build failed with exit code $LASTEXITCODE" }

$buildStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputDir = Join-Path $projectRoot "dist-qt-builds\$buildStamp"
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name PhoebeCleanerQt `
    --distpath $outputDir `
    --workpath (Join-Path $projectRoot 'build\pyinstaller') `
    --specpath (Join-Path $projectRoot 'build') `
    --add-data "$(Join-Path $projectRoot 'assets\phoebe\baked_animation_v6');assets\phoebe\baked_animation_v6" `
    --add-data "$(Join-Path $projectRoot 'assets\phoebe\baked_full_sequence_v8');assets\phoebe\baked_full_sequence_v8" `
    --add-data "$(Join-Path $projectRoot 'assets\phoebe\baked_front_sequences_v9');assets\phoebe\baked_front_sequences_v9" `
    --add-data "$(Join-Path $projectRoot 'assets\phoebe\spritesheets_v3_anchored\failure-bite.png');assets\phoebe\spritesheets_v3_anchored" `
    (Join-Path $projectRoot 'python_app\phoebe_cleaner\app.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$appDir = Join-Path $outputDir 'PhoebeCleanerQt'
Copy-Item -LiteralPath (Join-Path $shellBuild 'PhoebeShellExtension.dll') -Destination $appDir -Force
Set-Content -LiteralPath (Join-Path $projectRoot 'build\latest-python-app.txt') -Value $appDir -Encoding UTF8

Write-Host "Built: $(Join-Path $appDir 'PhoebeCleanerQt.exe')"
Write-Host "Shell bridge: $(Join-Path $appDir 'PhoebeShellExtension.dll')"
