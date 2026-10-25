$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'start_app.cmd'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'GoXTrade launcher was not found.' }
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not $desktop) { throw 'Windows Desktop folder could not be resolved.' }
$shortcutPath = Join-Path $desktop 'GoXTrade.lnk'
$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    if ($existing.TargetPath -ne $launcher) {
        $shortcutPath = Join-Path $desktop 'GoXTrade Native.lnk'
        if (Test-Path -LiteralPath $shortcutPath) {
            $existing = $shell.CreateShortcut($shortcutPath)
            if ($existing.TargetPath -ne $launcher) { throw 'An unrelated shortcut already uses the destination name.' }
        }
    }
}
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'GoXTrade - open, restart and manage the local trading interface'
$shortcut.WindowStyle = 1
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,20"
$shortcut.Save()
Write-Output "Created desktop shortcut: $shortcutPath"
