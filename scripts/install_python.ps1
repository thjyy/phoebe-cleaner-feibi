$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$latestBuildFile = Join-Path $projectRoot 'build\latest-python-app.txt'
if (Test-Path -LiteralPath $latestBuildFile) {
    $appDir = (Get-Content -LiteralPath $latestBuildFile -Raw).Trim()
} else {
    $appDir = Join-Path $projectRoot 'dist-qt\PhoebeCleanerQt'
}
$exePath = Join-Path $appDir 'PhoebeCleanerQt.exe'
$dllPath = Join-Path $appDir 'PhoebeShellExtension.dll'
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Executable not found: $exePath. Run scripts\build_python.ps1 first."
}
if (-not (Test-Path -LiteralPath $dllPath)) {
    throw "Shell bridge not found: $dllPath. Run scripts\build_python.ps1 first."
}

$title = -join @([char]0x53EC, [char]0x5524, [char]0x83F2, [char]0x6BD4, [char]0x6765, [char]0x6E05, [char]0x7406)
$clsid = '{7B0EE0AD-A02E-4B17-B55F-389713265BF2}'
$classKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Software\Classes\CLSID\$clsid\InprocServer32")
try {
    $classKey.SetValue('', $dllPath, [Microsoft.Win32.RegistryValueKind]::String)
    $classKey.SetValue('ThreadingModel', 'Apartment', [Microsoft.Win32.RegistryValueKind]::String)
} finally {
    $classKey.Dispose()
}

$approvedKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved')
try {
    $approvedKey.SetValue($clsid, 'Phoebe Cleaner Explorer Command', [Microsoft.Win32.RegistryValueKind]::String)
} finally {
    $approvedKey.Dispose()
}

$targets = @(
    'Software\Classes\*\shell\PhoebeCleaner',
    'Software\Classes\Directory\shell\PhoebeCleaner'
)

foreach ($target in $targets) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($target)
    try {
        $key.SetValue('', $title, [Microsoft.Win32.RegistryValueKind]::String)
        $key.SetValue('Icon', $exePath, [Microsoft.Win32.RegistryValueKind]::String)
        $key.SetValue('MultiSelectModel', 'Player', [Microsoft.Win32.RegistryValueKind]::String)
        $key.SetValue('ExplorerCommandHandler', $clsid, [Microsoft.Win32.RegistryValueKind]::String)
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree("$target\command", $false)
    } finally {
        $key.Dispose()
    }
}

$programsFolder = [Environment]::GetFolderPath('Programs')
$settingsTitle = -join @(
    [char]0x83F2, [char]0x6BD4, [char]0x6E05, [char]0x7406, [char]0x8BBE, [char]0x7F6E
)
$shortcutPath = Join-Path $programsFolder "$settingsTitle.lnk"
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exePath
$shortcut.Arguments = '--settings'
$shortcut.WorkingDirectory = $appDir
$shortcut.IconLocation = "$exePath,0"
$shortcut.Description = 'Choose concise, standard, or dramatic Phoebe animation timing.'
$shortcut.Save()

Write-Host 'Installed native Explorer bridge and Qt animation server.'
Write-Host "Settings shortcut: $shortcutPath"
Write-Host 'If Explorer cached the old verb, close and reopen File Explorer or restart Explorer once.'
