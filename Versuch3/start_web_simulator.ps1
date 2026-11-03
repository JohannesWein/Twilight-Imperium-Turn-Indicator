$ErrorActionPreference = 'Stop'

$adapter = Get-NetAdapter -Physical |
    Where-Object { $_.Status -eq 'Up' } |
    Select-Object -First 1

if (-not $adapter) {
    throw 'Kein aktiver physischer Netzwerkadapter gefunden.'
}

$lanAddress = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 |
    Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' } |
    Select-Object -First 1 -ExpandProperty IPAddress

if (-not $lanAddress) {
    throw "Keine verwendbare IPv4-Adresse auf Adapter '$($adapter.Name)' gefunden."
}

$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "Projekt-Python nicht gefunden: $python"
}

Write-Host "Starte TI4-Websimulator auf http://${lanAddress}:8090"
& $python (Join-Path $PSScriptRoot 'web_simulator.py') --host 0.0.0.0 --open-browser --browser-host $lanAddress