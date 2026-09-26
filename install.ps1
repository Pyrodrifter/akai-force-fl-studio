<#
.SYNOPSIS
    Installs (or removes) the Akai Force Live Control script for FL Studio.

.DESCRIPTION
    Copies device_AkaiForce.py and force_protocol.py into FL Studio's user
    "Hardware" folder, then checks that the Akai Network MIDI driver is present.
    force_plugin_maps.py (your own plugin knob pages) is copied only the first
    time, so your edits survive updates.

    Run it any of these ways:
      * Double-click install.bat (from the release zip)
      * .\install.ps1                 (from a clone / unzipped folder)
      * irm https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.ps1 | iex

.PARAMETER Uninstall
    Remove the script from FL Studio.

.PARAMETER HardwareDir
    Override FL Studio's Hardware folder (normally found automatically).
#>
param(
    [switch]$Uninstall,
    [string]$HardwareDir
)

$ErrorActionPreference = 'Stop'
$Repo = 'Pyrodrifter/akai-force-fl-studio'
$Branch = 'main'
$Files = @('device_AkaiForce.py', 'force_protocol.py')
$UserFiles = @('force_plugin_maps.py')     # installed once, never overwritten
$FolderName = 'Akai Force Live'

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }

# --------------------------------------------------------------------------- where FL keeps user scripts
function Get-FlHardwareDir {
    if ($HardwareDir) { return $HardwareDir }
    # FL stores its user-data root ("Shared data") in the registry; fall back to Documents\Image-Line.
    $root = $null
    try { $root = (Get-ItemProperty 'HKCU:\Software\Image-Line\Shared\Paths' -ErrorAction Stop).'Shared data' } catch { }
    if (-not $root) { $root = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Image-Line' }
    return Join-Path $root 'FL Studio\Settings\Hardware'
}

$hw = Get-FlHardwareDir
$dest = Join-Path $hw $FolderName

Say ''
Say 'Akai Force Live Control for FL Studio' 'Cyan'
Say '-------------------------------------' 'Cyan'

# --------------------------------------------------------------------------- uninstall
if ($Uninstall) {
    if (Test-Path $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
        Say "Removed $dest" 'Green'
        Say 'In FL Studio, set the "Akai Network - DAW Control" input back to (generic controller) or disable it.'
    } else {
        Say "Nothing to remove - $dest does not exist." 'Yellow'
    }
    return
}

# --------------------------------------------------------------------------- get the files (local copy or GitHub)
$here = if ($PSScriptRoot) { $PSScriptRoot } else { $null }
$local = $here -and ($Files | ForEach-Object { Test-Path (Join-Path $here $_) }) -notcontains $false
$staging = $null
if ($local) {
    $src = $here
    Say "Installing from $src"
} else {
    $staging = Join-Path ([IO.Path]::GetTempPath()) ('akai-force-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $staging | Out-Null
    Say "Downloading the latest script from github.com/$Repo ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    foreach ($f in $Files + $UserFiles) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/$Repo/$Branch/$f" -OutFile (Join-Path $staging $f)
    }
    $src = $staging
}

# --------------------------------------------------------------------------- install
if (-not (Test-Path $hw)) {
    Say "FL Studio's Hardware folder was not found at:" 'Yellow'
    Say "  $hw" 'Yellow'
    Say 'Creating it. If FL Studio uses a different user-data folder, re-run with -HardwareDir "<path>".' 'Yellow'
}
New-Item -ItemType Directory -Force $dest | Out-Null
foreach ($f in $Files) { Copy-Item -LiteralPath (Join-Path $src $f) -Destination $dest -Force }
foreach ($f in $UserFiles) {
    if (Test-Path (Join-Path $dest $f)) { Say "Kept your $f" }
    elseif (Test-Path (Join-Path $src $f)) { Copy-Item -LiteralPath (Join-Path $src $f) -Destination $dest }
}
if ($staging) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
$m = Select-String -LiteralPath (Join-Path $dest 'device_AkaiForce.py') -Pattern '^VERSION = "(.+)"' | Select-Object -First 1
$version = if ($m) { $m.Matches[0].Groups[1].Value } else { '(unknown)' }
Say "Installed version $version to:" 'Green'
Say "  $dest" 'Green'

# --------------------------------------------------------------------------- checks
Say ''
$fl = $null
try { $fl = (Get-ItemProperty 'HKCU:\Software\Image-Line\Shared\Paths' -ErrorAction Stop).'FL Studio' } catch { }
if ($fl -and (Test-Path $fl)) { Say "[ok] FL Studio found: $fl" 'Green' }
else { Say '[!!] FL Studio was not found in the registry. The script needs FL Studio 20.7 or newer (developed on FL Studio 2026).' 'Yellow' }

$ports = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'Akai Network' })
if ($ports.Count -gt 0) {
    Say '[ok] Akai Network MIDI driver found.' 'Green'
} else {
    Say '[!!] Akai Network MIDI driver NOT found.' 'Yellow'
    Say '     Install "Akai Network Driver" from the inMusic Software Center (My Hardware tab) or akaipro.com,' 'Yellow'
    Say '     restart the PC, then pair your Force in the Akai Network Driver app (Configured Remote Device).' 'Yellow'
}

if (Get-Process FL64, FL -ErrorAction SilentlyContinue) {
    Say '[i]  FL Studio is running: open Options > MIDI Settings and click "Update MIDI scripts" (or restart FL).' 'Cyan'
}

# --------------------------------------------------------------------------- next steps
Say ''
Say 'Next steps' 'Cyan'
Say '  1. FL Studio > Options > MIDI Settings:'
Say '       Input  "Akai Network - DAW Control": enable, Controller type = "Akai Force (Live Control)", Port = 1'
Say '       Output "Akai Network - DAW Control": Port = 1 (the same number)'
Say '  2. On the Force: press MENU, tap LIVE CONTROL.'
Say '  3. The knob screens flash PERFORM when it connects. Press LAUNCH to change pad modes.'
Say ''
Say "Manual: https://github.com/$Repo/releases/latest"
