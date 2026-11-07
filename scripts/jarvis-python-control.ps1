[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Check", "Stop")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

try {
    $runtimeConfigJson = & $pythonExe -c "import json; from app.core.config import HOST, PORT; print(json.dumps({'host': HOST, 'port': PORT}))"
    if ($LASTEXITCODE -ne 0) {
        throw "app.core.config retornou codigo $LASTEXITCODE"
    }
    $runtimeConfig = $runtimeConfigJson | ConvertFrom-Json
    $hostAddress = [string]$runtimeConfig.host
    $port = [int]$runtimeConfig.port
}
catch {
    Write-Error "Nao foi possivel resolver a configuracao canonica em app.core.config: $($_.Exception.Message)"
    exit 17
}

function Get-PortListener {
    $netstatPath = Join-Path $env:SystemRoot "System32\netstat.exe"
    $listenerPattern = "^\s*TCP\s+(\S+):${port}\s+\S+\s+LISTENING\s+(\d+)\s*$"

    foreach ($line in & $netstatPath -ano -p TCP) {
        if ($line -match $listenerPattern) {
            [pscustomobject]@{
                LocalAddress = $Matches[1]
                OwningProcess = [int]$Matches[2]
            }
        }
    }
}

function Test-JarvisHealth {
    try {
        $health = Invoke-RestMethod `
            -Uri "http://${hostAddress}:${port}/api/health" `
            -Method Get `
            -TimeoutSec 3
        return $health.components.server.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Get-VerifiedJarvisProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction Stop

    if ($null -eq $process) {
        return $null
    }

    if ($process.ProcessName -notin @("python", "pythonw")) {
        return $null
    }

    return $process
}

$portListeners = @(Get-PortListener)
$listeners = @(
    $portListeners |
        Where-Object { $_.LocalAddress -eq $hostAddress }
)

if ($Action -eq "Check") {
    if ($portListeners.Count -eq 0) {
        Write-Host "Porta ${port} livre."
        exit 0
    }

    if ($listeners.Count -gt 0 -and (Test-JarvisHealth)) {
        Write-Host "Jarvis Python ja esta rodando em http://${hostAddress}:${port}."
        Write-Host "Nenhuma segunda instancia foi criada."
        exit 10
    }

    Write-Error "A porta ${port} esta ocupada por outro processo. O Jarvis Python nao foi iniciado."
    exit 11
}

if ($listeners.Count -eq 0) {
    if ($portListeners.Count -gt 0) {
        Write-Host "Jarvis Python ja estava desligado; a porta ${port} pertence a outro processo."
    }
    else {
        Write-Host "Jarvis Python ja estava desligado."
    }
    exit 0
}

$listenerProcessIds = @(
    $listeners |
        Select-Object -ExpandProperty OwningProcess -Unique
)

if ($listenerProcessIds.Count -ne 1) {
    Write-Error "Nao foi possivel identificar com seguranca um unico processo na porta ${port}."
    exit 12
}

$listenerProcessId = [int]$listenerProcessIds[0]

if (-not (Test-JarvisHealth)) {
    Write-Error "O processo da porta ${port} nao respondeu como Jarvis FastAPI. Nada foi encerrado."
    exit 13
}

$jarvisProcess = Get-VerifiedJarvisProcess -ProcessId $listenerProcessId
if ($null -eq $jarvisProcess) {
    Write-Error "O processo da porta ${port} nao corresponde ao Jarvis Python. Nada foi encerrado."
    exit 14
}

try {
    $shutdown = Invoke-RestMethod `
        -Uri "http://${hostAddress}:${port}/api/jarvis/shutdown" `
        -Method Post `
        -TimeoutSec 3
}
catch {
    Write-Error "O Jarvis foi identificado, mas recusou a solicitacao de shutdown gracioso. Nada foi forcado."
    exit 15
}

if ($shutdown.status -ne "shutting_down") {
    Write-Error "O Jarvis respondeu sem confirmar o shutdown gracioso. Nada foi forcado."
    exit 15
}

$deadline = [DateTime]::UtcNow.AddSeconds(10)
do {
    Start-Sleep -Milliseconds 200
    $remainingListeners = @(
        Get-PortListener |
            Where-Object { $_.LocalAddress -eq $hostAddress }
    )
} while ($remainingListeners.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)

if ($remainingListeners.Count -gt 0) {
    Write-Error "O shutdown gracioso foi solicitado, mas a porta ${port} nao ficou livre no prazo. Nada foi forcado."
    exit 16
}

Write-Host "Jarvis Python encerrado com sucesso. Porta ${port} livre."
exit 0
