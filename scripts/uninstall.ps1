$ErrorActionPreference = 'Stop'

$targets = @(
    'Software\Classes\*\shell\PhoebeCleaner',
    'Software\Classes\Directory\shell\PhoebeCleaner',
    'Software\PhoebeCleaner'
)

foreach ($target in $targets) {
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($target, $false)
}

Write-Host 'Phoebe Cleaner context menu and local random-choice history removed.'
