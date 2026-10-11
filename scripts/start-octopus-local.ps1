param(
    [int]$Port = 8188
)

$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$portableRoot = Join-Path $sourceRoot 'desktop/portable/release/Octop-windows-amd64'
$pythonPath = Join-Path $portableRoot 'runtime/python.exe'
$launchPath = Join-Path $portableRoot 'launch.py'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath $launchPath)) {
    throw 'Build the Windows portable package before starting the local preview.'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Output "An existing service is listening at http://127.0.0.1:$Port/"
    exit 0
}
$runtimeRoot = Join-Path $sourceRoot '.runtime'
$profileRoot = Join-Path $runtimeRoot 'dev'
New-Item -ItemType Directory -Force -Path $profileRoot | Out-Null
$previousOctopHome = $env:OCTOP_HOME
try {
    $env:OCTOP_HOME = $profileRoot
    $env:PYTHONUTF8 = '1'
    $process = Start-Process -FilePath $pythonPath -ArgumentList @(
        ('"' + $launchPath + '"'), 'run', '--host', '127.0.0.1', '--port', "$Port"
    ) -WorkingDirectory $sourceRoot -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput (Join-Path $runtimeRoot 'portable-host.log') `
      -RedirectStandardError (Join-Path $runtimeRoot 'portable-host-errors.log')
    Write-Output "Started local Octopus host (PID $($process.Id)): http://127.0.0.1:$Port/"
} finally {
    $env:OCTOP_HOME = $previousOctopHome
}
