$ErrorActionPreference = 'Stop'

$targets = @(
    'Software\Classes\*\shell\PhoebeCleaner',
    'Software\Classes\Directory\shell\PhoebeCleaner',
    'Software\PhoebeCleaner',
    'Software\Classes\CLSID\{7B0EE0AD-A02E-4B17-B55F-389713265BF2}'
)

foreach ($target in $targets) {
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($target, $false)
}

$approvedKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey(
    'Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved',
    $true
)
if ($approvedKey) {
    try {
        $approvedKey.DeleteValue('{7B0EE0AD-A02E-4B17-B55F-389713265BF2}', $false)
    } finally {
        $approvedKey.Dispose()
    }
}

$settingsTitle = -join @(
    [char]0x83F2, [char]0x6BD4, [char]0x6E05, [char]0x7406, [char]0x8BBE, [char]0x7F6E
)
$settingsShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) "$settingsTitle.lnk"
if (Test-Path -LiteralPath $settingsShortcut) {
    Remove-Item -LiteralPath $settingsShortcut -Force
}

Write-Host 'Phoebe Cleaner context menu and local random-choice history removed.'
