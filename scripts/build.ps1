$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $projectRoot 'build'
$distDir = Join-Path $projectRoot 'dist'
$assetSource = Join-Path $projectRoot 'assets\phoebe'
$assetDestination = Join-Path $distDir 'assets\phoebe'

$cmake = (Get-Command cmake -ErrorAction Stop).Source
$toolDir = Split-Path -Parent $cmake
$ninja = Join-Path $toolDir 'ninja.exe'
$compiler = Join-Path $toolDir 'g++.exe'

& $cmake -S $projectRoot -B $buildDir -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninja" "-DCMAKE_CXX_COMPILER=$compiler" -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed with exit code $LASTEXITCODE" }
& $cmake --build $buildDir --config Release
if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
Copy-Item -LiteralPath (Join-Path $buildDir 'PhoebeCleaner.exe') -Destination (Join-Path $distDir 'PhoebeCleaner.exe') -Force
New-Item -ItemType Directory -Force -Path $assetDestination | Out-Null
Copy-Item -LiteralPath (Join-Path $assetSource 'spritesheets') -Destination $assetDestination -Recurse -Force
Copy-Item -LiteralPath (Join-Path $assetSource 'spritesheets_v2') -Destination $assetDestination -Recurse -Force
Copy-Item -LiteralPath (Join-Path $assetSource 'framecache') -Destination $assetDestination -Recurse -Force
Copy-Item -LiteralPath (Join-Path $assetSource 'animation-spec.json') -Destination $assetDestination -Force

Write-Host "Built: $(Join-Path $distDir 'PhoebeCleaner.exe')"
