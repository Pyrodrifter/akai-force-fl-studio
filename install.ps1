# Copies the Force script into FL Studio's user hardware folder.
$dest = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Image-Line\FL Studio\Settings\Hardware\Akai Force Live'
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'device_AkaiForce.py'), (Join-Path $PSScriptRoot 'force_protocol.py') $dest -Force
Write-Output "Installed to $dest"
