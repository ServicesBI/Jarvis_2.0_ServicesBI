[CmdletBinding()]
param(
    [string]$Destination = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$launcherPath = Join-Path $projectRoot "Ligar JARVIS.bat"
$iconPath = Join-Path $projectRoot "assets\icons\jarvis-desktop.ico"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Inicializador oficial do Jarvis nao encontrado: $launcherPath"
}

if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Icone oficial do Jarvis nao encontrado: $iconPath"
}

if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $Destination "Jarvis.lnk"
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "Inicia o Jarvis"
$shortcut.WindowStyle = 1
$shortcut.Save()

foreach ($legacyName in @("Ligar Jarvis.lnk", "Desligar Jarvis.lnk")) {
    $legacyPath = Join-Path $Destination $legacyName
    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
        Remove-Item -LiteralPath $legacyPath -Force
    }
}

Write-Host "Atalho criado ou atualizado: $shortcutPath"
