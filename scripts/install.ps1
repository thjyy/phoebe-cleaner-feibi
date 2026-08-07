$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $projectRoot 'dist\PhoebeCleaner.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Executable not found: $exePath. Run scripts\build.ps1 first."
}

$title = -join @([char]0x53EC, [char]0x5524, [char]0x83F2, [char]0x6BD4, [char]0x6765, [char]0x6E05, [char]0x7406)
$command = [char]34 + $exePath + [char]34 + ' ' + [char]34 + '%1' + [char]34
$targets = @(
    'Software\Classes\*\shell\PhoebeCleaner',
    'Software\Classes\Directory\shell\PhoebeCleaner'
)

foreach ($target in $targets) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($target)
    try {
        $key.SetValue('', $title, [Microsoft.Win32.RegistryValueKind]::String)
        $key.SetValue('Icon', $exePath, [Microsoft.Win32.RegistryValueKind]::String)
        $key.SetValue('MultiSelectModel', 'Single', [Microsoft.Win32.RegistryValueKind]::String)
        $commandKey = $key.CreateSubKey('command')
        try {
            $commandKey.SetValue('', $command, [Microsoft.Win32.RegistryValueKind]::String)
        } finally {
            $commandKey.Dispose()
        }
    } finally {
        $key.Dispose()
    }
}

Write-Host 'Installed. On Windows 11, right-click a file and choose Show more options.'
