param(
    [string]$WorkspaceRoot = "c:\Git\Twilight-Imperium-Turn-Indicator\Versuch3",
    [string]$MpremoteExe = "c:\Git\Twilight-Imperium-Turn-Indicator\.venv\Scripts\mpremote.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $MpremoteExe)) {
    throw "mpremote not found: $MpremoteExe"
}

Set-Location $WorkspaceRoot

$cfg = Join-Path $WorkspaceRoot "config.py"
$boot = Join-Path $WorkspaceRoot "boot.py"
if (-not (Test-Path $cfg)) { throw "Missing file: $cfg" }
if (-not (Test-Path $boot)) { throw "Missing file: $boot" }

# Raspberry Pi Pico USB VID/PID
$usbPicos = Get-CimInstance Win32_PnPEntity |
    Where-Object { $_.PNPDeviceID -match 'VID_2E8A&PID_0005' -and $_.Name -match '\(COM\d+\)' }

$ports = @()
foreach ($d in $usbPicos) {
    if ($d.Name -match '\((COM\d+)\)') {
        $ports += $Matches[1]
    }
}
$ports = $ports | Sort-Object -Unique

if (-not $ports -or $ports.Count -eq 0) {
    Write-Output "NO_PICO_PORTS_FOUND"
    exit 0
}

Write-Output ("FOUND_PORTS: " + ($ports -join ', '))

foreach ($port in $ports) {
    Write-Output ("=== " + $port + " ===")

    & $MpremoteExe connect $port cp $cfg :config.py
    $copyConfigExit = $LASTEXITCODE
    Write-Output ("COPY_CONFIG_EXIT=" + $copyConfigExit)
    if ($copyConfigExit -ne 0) {
        Write-Output ("FAILED_PORT=" + $port + " STEP=config")
        continue
    }

    & $MpremoteExe connect $port cp $boot :boot.py
    $copyBootExit = $LASTEXITCODE
    Write-Output ("COPY_BOOT_EXIT=" + $copyBootExit)
    if ($copyBootExit -ne 0) {
        Write-Output ("FAILED_PORT=" + $port + " STEP=boot")
        continue
    }

    & $MpremoteExe connect $port exec "import machine; machine.reset()"
    $resetExit = $LASTEXITCODE
    Write-Output ("RESET_EXIT=" + $resetExit)

    if ($resetExit -eq 0) {
        Write-Output ("UPDATED_OK=" + $port)
    } else {
        Write-Output ("FAILED_PORT=" + $port + " STEP=reset")
    }
}
