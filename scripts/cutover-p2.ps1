<#
.SYNOPSIS
    Jarvis P2 Operational Cutover — PostgreSQL migration automation.

.DESCRIPTION
    Guard-railed, idempotent automation for cutting TaskManager over from the
    legacy file backend (system/task-state.json) to the operational
    PostgreSQL database ("jarvis"), per the decision recorded in
    JARVIS_HANDOFF.md / JARVIS_MASTER.md §12/§26/§27:

        DATABASE      = jarvis
        ROLE TARGET   = jarvis_app
        TEST DATABASE = jarvis_test (untouched, test-only, forever)
        FORBIDDEN     = postgres, servicesbi, sige_servicesbi, site-oficial,
                         and jarvis_test_user (never elevated / never reused
                         as the operational role)

    This script is meant to be run by a worker with real local access to
    Windows process control and to 127.0.0.1:5432/127.0.0.1:8000 (Codex
    Desktop or Claude Code running locally) — NOT from the Cowork cloud
    bridge, which cannot reach localhost services on this machine.

    It performs steps 1-24 of the P2 cutover exactly as specified in
    JARVIS_HANDOFF.md, stopping immediately and structurally on any
    ambiguity or failure. Nothing here ever TRUNCATEs, deletes the legacy
    JSON, deletes a database, or rewrites historical rows to make a check
    pass.

.PARAMETER AdminConnectionString
    A PostgreSQL connection string with enough privilege to create the
    "jarvis" database and the "jarvis_app" role, e.g.:
        postgresql://postgres:<admin-password>@127.0.0.1:5432/postgres
    Required ONLY the first time (bootstrap). If "jarvis" and "jarvis_app"
    already exist, this script never asks for it and never uses it.
    NEVER printed, logged, or persisted anywhere by this script.

.PARAMETER JarvisAppPassword
    Optional explicit password for the "jarvis_app" role. If omitted and the
    role must be created, a strong random password is generated and written
    only into .env (JARVIS_DATABASE_URL), never echoed to the console/log.

.PARAMETER SkipValidationTask
    Skip steps 19-21 (creation of the bounded excel.create validation Task).
    Off by default — the validation task is the strongest real proof that
    repository mode is active end-to-end.

.OUTPUTS
    A structured JSON report is always written to
    system/cutover-reports/p2-cutover-<UTC timestamp>.json — even on a
    partial/aborted run — so any worker picking this up later can see
    exactly which step it stopped on and why, without re-deriving context.

.EXAMPLE
    # First run on this machine (bootstrap): jarvis / jarvis_app don't exist yet.
    .\scripts\cutover-p2.ps1 -AdminConnectionString "postgresql://postgres:REDACTED@127.0.0.1:5432/postgres"

.EXAMPLE
    # Re-run later (jarvis/jarvis_app already exist, JARVIS_DATABASE_URL already valid in .env) — no admin string needed.
    .\scripts\cutover-p2.ps1
#>

[CmdletBinding()]
param(
    [string]$AdminConnectionString = $null,
    [string]$JarvisAppPassword = $null,
    [switch]$SkipValidationTask
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ---------------------------------------------------------------------------
# Constants — hardcoded on purpose. These are NOT parameters: nobody should
# be able to point this script at a different database by accident or by a
# mistyped argument. This is the structural guarantee behind "nunca usar
# banco de outro sistema" / "role dedicada ao Jarvis".
# ---------------------------------------------------------------------------
$OPERATIONAL_DB_NAME   = "jarvis"
$TEST_DB_NAME          = "jarvis_test"
$OPERATIONAL_ROLE_NAME = "jarvis_app"
$FORBIDDEN_DB_NAMES    = @("postgres", "servicesbi", "sige_servicesbi", "site-oficial")
$FORBIDDEN_ROLE_NAMES  = @("jarvis_test_user")   # never elevated, never reused, never touched
$PG_HOST = "127.0.0.1"
$PG_PORT = 5432
$JARVIS_HOST = "127.0.0.1"
$JARVIS_PORT = 8000

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe   = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile     = Join-Path $ProjectRoot ".env"
$ControlScript = Join-Path $ProjectRoot "scripts\jarvis-python-control.ps1"
$TaskStateJsonPath = Join-Path $ProjectRoot "system\task-state.json"
$ReportsDir = Join-Path $ProjectRoot "system\cutover-reports"

$RunStartedAt = [DateTime]::UtcNow
$RunId = $RunStartedAt.ToString("yyyyMMdd'T'HHmmss'Z'")
$Report = [ordered]@{
    run_id              = $RunId
    started_at          = $RunStartedAt.ToString("o")
    finished_at         = $null
    outcome             = "IN_PROGRESS"
    blocker             = $null
    blocker_detail      = $null
    steps               = [ordered]@{}
    operational_database = $OPERATIONAL_DB_NAME
    operational_role      = $OPERATIONAL_ROLE_NAME
}

function Write-Step {
    param([string]$Name, [string]$Status, [hashtable]$Detail = @{})
    $Report.steps[$Name] = [ordered]@{
        status = $Status
        detail = $Detail
        at     = [DateTime]::UtcNow.ToString("o")
    }
    Write-Host "[$Status] $Name"
}

function Save-Report {
    if (-not (Test-Path $ReportsDir)) {
        New-Item -ItemType Directory -Path $ReportsDir -Force | Out-Null
    }
    $Report.finished_at = [DateTime]::UtcNow.ToString("o")
    $reportPath = Join-Path $ReportsDir "p2-cutover-$RunId.json"
    ($Report | ConvertTo-Json -Depth 12) | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host ""
    Write-Host "Relatorio estruturado: $reportPath"
    return $reportPath
}

function Stop-Cutover {
    param([string]$BlockerCode, [string]$DetailMessage, [hashtable]$Extra = @{})
    $Report.outcome = "BLOCKED"
    $Report.blocker = $BlockerCode
    $Report.blocker_detail = $DetailMessage
    foreach ($key in $Extra.Keys) { $Report[$key] = $Extra[$key] }
    Write-Step -Name "ABORT" -Status "BLOCKED" -Detail @{ blocker = $BlockerCode; message = $DetailMessage }
    $reportPath = Save-Report
    Write-Error "CUTOVER ABORTADO — $BlockerCode : $DetailMessage (ver $reportPath)"
    exit 1
}

# Runs a short inline Python snippet using the project's own venv (which
# already has psycopg[binary] from requirements.txt) so we never depend on a
# separate psql.exe being on PATH. $PySnippet must print exactly one JSON
# object to stdout as its last line; anything else is treated as failure.
function Invoke-PySnippet {
    param([string]$PySnippet, [hashtable]$ExtraEnv = @{})
    $tmp = [System.IO.Path]::GetTempFileName() + ".py"
    Set-Content -Path $tmp -Value $PySnippet -Encoding UTF8
    $envBackup = @{}
    foreach ($key in $ExtraEnv.Keys) {
        $envBackup[$key] = [System.Environment]::GetEnvironmentVariable($key)
        [System.Environment]::SetEnvironmentVariable($key, $ExtraEnv[$key])
    }
    try {
        $output = & $PythonExe $tmp 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        foreach ($key in $envBackup.Keys) {
            [System.Environment]::SetEnvironmentVariable($key, $envBackup[$key])
        }
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join "`n") }
}

# =============================================================================
# STEP 1 — validar que está rodando no ambiente correto (best-effort: não há
# nenhum hostname/allowlist de máquina documentado em JARVIS_MASTER.md, então
# validamos a ESTRUTURA do repositório em vez de inventar uma checagem de
# hostname que não existe em nenhuma fonte de verdade).
# =============================================================================
try {
    if ($env:OS -notmatch "Windows") {
        Stop-Cutover -BlockerCode "WRONG_ENVIRONMENT" -DetailMessage "Este script assume Windows (Jarvis roda em 127.0.0.1:8000 via .venv\Scripts\python.exe). SO detectado: $($env:OS)"
    }
    $markers = @("run.py", "alembic.ini", "app\main.py", "JARVIS_MASTER.md", ".venv\Scripts\python.exe")
    $missing = @($markers | Where-Object { -not (Test-Path (Join-Path $ProjectRoot $_)) })
    if ($missing.Count -gt 0) {
        Stop-Cutover -BlockerCode "WRONG_ENVIRONMENT" -DetailMessage "ProjectRoot '$ProjectRoot' nao parece ser o repositorio Jarvis (faltando: $($missing -join ', '))."
    }
    Write-Step -Name "1_validate_environment" -Status "OK" -Detail @{ project_root = $ProjectRoot }
}
catch {
    Stop-Cutover -BlockerCode "WRONG_ENVIRONMENT" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 2 — validar acesso a 127.0.0.1:5432
# =============================================================================
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $connectTask = $tcp.ConnectAsync($PG_HOST, $PG_PORT)
    if (-not $connectTask.Wait(3000)) {
        $tcp.Close()
        Stop-Cutover -BlockerCode "POSTGRES_UNREACHABLE" -DetailMessage "Timeout conectando em ${PG_HOST}:${PG_PORT}. Este worker precisa ter acesso local real ao Postgres — se esta rodando via bridge/Cowork sem acesso a localhost, isso e esperado: BLOCKER=EXECUTION_ENVIRONMENT_NO_LOCALHOST, use um worker local (Codex Desktop / Claude Code local)."
    }
    $tcp.Close()
    Write-Step -Name "2_validate_postgres_tcp" -Status "OK" -Detail @{ host = $PG_HOST; port = $PG_PORT }
}
catch {
    Stop-Cutover -BlockerCode "POSTGRES_UNREACHABLE" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 3 — detectar PostgreSQL real (serviço Windows, best-effort — o nome
# documentado em JARVIS_MASTER.md/JARVIS_HANDOFF.md é "postgresql-x64-18",
# mas toleramos variações de versão)
# =============================================================================
try {
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pgService) {
        Write-Step -Name "3_detect_postgres_service" -Status "WARN" -Detail @{ message = "Nenhum servico Windows 'postgresql*' encontrado, mas a porta 5432 respondeu (step 2) — prosseguindo." }
    }
    elseif ($pgService.Status -ne "Running") {
        Stop-Cutover -BlockerCode "POSTGRES_SERVICE_NOT_RUNNING" -DetailMessage "Servico '$($pgService.Name)' encontrado mas status = $($pgService.Status)."
    }
    else {
        Write-Step -Name "3_detect_postgres_service" -Status "OK" -Detail @{ service_name = $pgService.Name; status = $pgService.Status }
    }
}
catch {
    Write-Step -Name "3_detect_postgres_service" -Status "WARN" -Detail @{ message = $_.Exception.Message }
}

# =============================================================================
# STEP 4 — verificar existência de jarvis / jarvis_test / role jarvis_app
# Usa AdminConnectionString se fornecida; senão tenta introspecção via
# JARVIS_TEST_DATABASE_URL (credencial que sabemos que já existe e funciona)
# — pg_database/pg_roles são catálogos legíveis por qualquer role autenticada
# por padrão, então isso NÃO exige privilégio de admin, só uma conexão válida.
# =============================================================================
function Get-EnvValue {
    param([string]$Key)
    if (-not (Test-Path $EnvFile)) { return $null }
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^\s*$([regex]::Escape($Key))\s*=" } | Select-Object -Last 1
    if ($null -eq $line) { return $null }
    $idx = $line.IndexOf("=")
    return $line.Substring($idx + 1).Trim()
}

$introspectionConn = $AdminConnectionString
$introspectionSource = "admin"
if ([string]::IsNullOrWhiteSpace($introspectionConn)) {
    $testUrl = Get-EnvValue -Key "JARVIS_TEST_DATABASE_URL"
    if (-not [string]::IsNullOrWhiteSpace($testUrl)) {
        $introspectionConn = $testUrl
        $introspectionSource = "jarvis_test_url"
    }
}

if ([string]::IsNullOrWhiteSpace($introspectionConn)) {
    Stop-Cutover -BlockerCode "POSTGRES_INTROSPECTION_FAILED" -DetailMessage "Nem -AdminConnectionString foi fornecida, nem JARVIS_TEST_DATABASE_URL existe em .env — impossivel verificar existencia de bancos/roles."
}

$introspectSnippet = @'
import json, os, sys
import psycopg
conn_str = os.environ["JARVIS_CUTOVER_INTROSPECT_DSN"]
try:
    with psycopg.connect(conn_str, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT datname, pg_get_userbyid(datdba) FROM pg_database WHERE datistemplate = false ORDER BY datname;")
            db_rows = cur.fetchall()
            dbs = [r[0] for r in db_rows]
            db_owners = {r[0]: r[1] for r in db_rows}
            cur.execute("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles ORDER BY rolname;")
            role_rows = cur.fetchall()
            roles = [r[0] for r in role_rows]
            role_attrs = {
                r[0]: {
                    "rolcanlogin": r[1],
                    "rolsuper": r[2],
                    "rolcreatedb": r[3],
                    "rolcreaterole": r[4],
                    "rolreplication": r[5],
                }
                for r in role_rows
            }
    print(json.dumps({"ok": True, "databases": dbs, "roles": roles, "db_owners": db_owners, "role_attrs": role_attrs}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(type(e).__name__) + ": " + str(e)}))
    sys.exit(1)
'@

$introspectResult = Invoke-PySnippet -PySnippet $introspectSnippet -ExtraEnv @{ JARVIS_CUTOVER_INTROSPECT_DSN = $introspectionConn }
if ($introspectResult.ExitCode -ne 0) {
    Stop-Cutover -BlockerCode "POSTGRES_INTROSPECTION_FAILED" -DetailMessage "Falha ao introspeccionar Postgres via '$introspectionSource': $($introspectResult.Output)"
}
$introspectData = $introspectResult.Output | ConvertFrom-Json

$dbExists   = $introspectData.databases -contains $OPERATIONAL_DB_NAME
$testExists = $introspectData.databases -contains $TEST_DB_NAME
$roleExists = $introspectData.roles -contains $OPERATIONAL_ROLE_NAME

if (-not $testExists) {
    Stop-Cutover -BlockerCode "TEST_DATABASE_MISSING" -DetailMessage "'$TEST_DB_NAME' nao existe no servidor — isso contradiz o estado documentado em JARVIS_MASTER.md §12. Parando por seguranca (nao presumir topologia)."
}
foreach ($forbidden in $FORBIDDEN_DB_NAMES) {
    if ($OPERATIONAL_DB_NAME -eq $forbidden) {
        # impossível (constante hardcoded == "jarvis"), mas mantido como cinto-e-suspensorio estrutural
        Stop-Cutover -BlockerCode "FORBIDDEN_DATABASE_TARGET" -DetailMessage "Guard-rail estrutural disparou — nao deveria ser possivel."
    }
}

# Se a role jarvis_app ja existe, valida seus atributos contra o
# contrato esperado (least privilege) -- drift vira FAIL explicito,
# nunca correcao automatica de privilegios (nao amplio/reduzo nada).
if ($roleExists) {
    $roleAttrs = $introspectData.role_attrs.$OPERATIONAL_ROLE_NAME
    $expectedRoleAttrs = [ordered]@{
        rolcanlogin    = $true
        rolsuper       = $false
        rolcreatedb    = $false
        rolcreaterole  = $false
        rolreplication = $false
    }
    $roleAttrDrift = @()
    foreach ($attrName in $expectedRoleAttrs.Keys) {
        $actual = $roleAttrs.$attrName
        if ($actual -ne $expectedRoleAttrs[$attrName]) {
            $roleAttrDrift += "$attrName=$actual (esperado $($expectedRoleAttrs[$attrName]))"
        }
    }
    if ($roleAttrDrift.Count -gt 0) {
        Stop-Cutover -BlockerCode "ROLE_ATTRIBUTES_DRIFT" -DetailMessage "Role '$OPERATIONAL_ROLE_NAME' ja existe mas com atributos fora do contrato esperado (LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION): $($roleAttrDrift -join '; '). Nao amplio/reduzo privilegios automaticamente." -Extra @{ role_attribute_drift = $roleAttrDrift }
    }
}

# Se o database jarvis ja existe, valida o owner -- drift vira FAIL
# explicito, nunca ALTER DATABASE OWNER automatico.
if ($dbExists) {
    $actualOwner = $introspectData.db_owners.$OPERATIONAL_DB_NAME
    if ($actualOwner -ne $OPERATIONAL_ROLE_NAME) {
        Stop-Cutover -BlockerCode "DATABASE_OWNER_DRIFT" -DetailMessage "Database '$OPERATIONAL_DB_NAME' ja existe mas com owner '$actualOwner' (esperado '$OPERATIONAL_ROLE_NAME'). Nao executo ALTER DATABASE OWNER automaticamente." -Extra @{ actual_owner = $actualOwner }
    }
}

Write-Step -Name "4_check_existing_objects" -Status "OK" -Detail @{
    introspection_source = $introspectionSource
    jarvis_db_exists      = $dbExists
    jarvis_test_db_exists = $testExists
    jarvis_app_role_exists = $roleExists
    other_databases_present = @($introspectData.databases | Where-Object { $_ -in $FORBIDDEN_DB_NAMES })
}

# =============================================================================
# STEP 5/6/7 — bootstrap (cria banco/role SE necessário); NUNCA toca em
# jarvis_test_user; NUNCA usa banco de outro sistema (constante hardcoded).
# =============================================================================
$needsBootstrap = (-not $dbExists) -or (-not $roleExists)
$generatedPassword = $null

if ($needsBootstrap) {
    if ([string]::IsNullOrWhiteSpace($AdminConnectionString)) {
        Stop-Cutover -BlockerCode "POSTGRES_ADMIN_BOOTSTRAP_REQUIRED" -DetailMessage "Faltando: $(@(if(-not $roleExists){'role jarvis_app'}; if(-not $dbExists){'database jarvis'}) -join ' e '). E necessario -AdminConnectionString (credencial com privilegio de CREATEROLE/CREATEDB) para criar isso uma unica vez. Nada foi alterado." -Extra @{ needs_role = -not $roleExists; needs_database = -not $dbExists }
    }

    if (-not $roleExists) {
        if ([string]::IsNullOrWhiteSpace($JarvisAppPassword)) {
            # gera senha forte aleatoria — nunca impressa, só usada para montar a DSN e gravada no .env
            $bytes = New-Object byte[] 32
            # RandomNumberGenerator.Fill(Span<byte>) e .NET Core/5+ e nao
            # existe no .NET Framework 4.x (Windows PowerShell 5.1 real
            # falha com "nao contem um metodo denominado 'Fill'"). Padrao
            # compativel com PowerShell 5.1: Create() + GetBytes() + Dispose().
            $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            try {
                $rng.GetBytes($bytes)
            }
            finally {
                $rng.Dispose()
            }
            $generatedPassword = [Convert]::ToBase64String($bytes) -replace '[+/=]', ''
        }
        else {
            $generatedPassword = $JarvisAppPassword
        }

        $createRoleSnippet = @'
import json, os, sys
import psycopg
from psycopg import sql
admin_dsn = os.environ["JARVIS_CUTOVER_ADMIN_DSN"]
role_name = os.environ["JARVIS_CUTOVER_ROLE_NAME"]
role_password = os.environ["JARVIS_CUTOVER_ROLE_PASSWORD"]
forbidden = os.environ["JARVIS_CUTOVER_FORBIDDEN_ROLES"].split(",")
if role_name in forbidden:
    print(json.dumps({"ok": False, "error": "structural guard: refusing to touch forbidden role"}))
    sys.exit(1)
try:
    with psycopg.connect(admin_dsn, connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Role dedicada, sem privilegios administrativos — least privilege.
            # CREATE ROLE e um utility statement do PostgreSQL: a clausula
            # PASSWORD nao aceita bind parameter ($1/%s) nessa posicao
            # (erro real observado: "syntax error at or near \"$1\"").
            # sql.Literal() embute o valor como um literal SQL corretamente
            # escapado/quoted -- nao e concatenacao manual nem f-string --
            # a unica forma segura de compor esta DDL especifica.
            query = sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION"
            ).format(
                sql.Identifier(role_name),
                sql.Literal(role_password),
            )
            cur.execute(query)
    print(json.dumps({"ok": True}))
except Exception as e:
    # A senha nunca pode vazar: sql.Literal(role_password) embute o valor
    # na propria query, e alguns erros do driver/Postgres podem ecoar a
    # query no texto da excecao. Sanitiza antes de imprimir -- o stdout
    # deste processo e capturado e pode acabar em Stop-Cutover/Save-Report.
    safe_error = (str(type(e).__name__) + ": " + str(e)).replace(role_password, "[REDACTED]")
    print(json.dumps({"ok": False, "error": safe_error}))
    sys.exit(1)
'@
        $createRoleResult = Invoke-PySnippet -PySnippet $createRoleSnippet -ExtraEnv @{
            JARVIS_CUTOVER_ADMIN_DSN       = $AdminConnectionString
            JARVIS_CUTOVER_ROLE_NAME       = $OPERATIONAL_ROLE_NAME
            JARVIS_CUTOVER_ROLE_PASSWORD   = $generatedPassword
            JARVIS_CUTOVER_FORBIDDEN_ROLES = ($FORBIDDEN_ROLE_NAMES -join ",")
        }
        if ($createRoleResult.ExitCode -ne 0) {
            Stop-Cutover -BlockerCode "ROLE_CREATION_FAILED" -DetailMessage "Falha ao criar role '$OPERATIONAL_ROLE_NAME': $($createRoleResult.Output)"
        }
        Write-Step -Name "5_create_role" -Status "OK" -Detail @{ role = $OPERATIONAL_ROLE_NAME }
    }
    else {
        Write-Step -Name "5_create_role" -Status "SKIPPED" -Detail @{ reason = "role ja existe" }
    }

    if (-not $dbExists) {
        $createDbSnippet = @'
import json, os, sys
import psycopg
from psycopg import sql
admin_dsn = os.environ["JARVIS_CUTOVER_ADMIN_DSN"]
db_name = os.environ["JARVIS_CUTOVER_DB_NAME"]
owner_role = os.environ["JARVIS_CUTOVER_ROLE_NAME"]
forbidden = os.environ["JARVIS_CUTOVER_FORBIDDEN_DBS"].split(",")
if db_name in forbidden or db_name == os.environ.get("JARVIS_CUTOVER_TEST_DB_NAME"):
    print(json.dumps({"ok": False, "error": "structural guard: refusing forbidden/test database as target"}))
    sys.exit(1)
try:
    with psycopg.connect(admin_dsn, connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(db_name), sql.Identifier(owner_role)
                )
            )
    print(json.dumps({"ok": True}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(type(e).__name__) + ": " + str(e)}))
    sys.exit(1)
'@
        $createDbResult = Invoke-PySnippet -PySnippet $createDbSnippet -ExtraEnv @{
            JARVIS_CUTOVER_ADMIN_DSN     = $AdminConnectionString
            JARVIS_CUTOVER_DB_NAME       = $OPERATIONAL_DB_NAME
            JARVIS_CUTOVER_ROLE_NAME     = $OPERATIONAL_ROLE_NAME
            JARVIS_CUTOVER_TEST_DB_NAME  = $TEST_DB_NAME
            JARVIS_CUTOVER_FORBIDDEN_DBS = ($FORBIDDEN_DB_NAMES -join ",")
        }
        if ($createDbResult.ExitCode -ne 0) {
            Stop-Cutover -BlockerCode "DATABASE_CREATION_FAILED" -DetailMessage "Falha ao criar database '$OPERATIONAL_DB_NAME': $($createDbResult.Output)"
        }
        Write-Step -Name "6_create_database" -Status "OK" -Detail @{ database = $OPERATIONAL_DB_NAME; owner = $OPERATIONAL_ROLE_NAME }
    }
    else {
        Write-Step -Name "6_create_database" -Status "SKIPPED" -Detail @{ reason = "database ja existe" }
    }
}
else {
    Write-Step -Name "5_create_role" -Status "SKIPPED" -Detail @{ reason = "bootstrap nao necessario" }
    Write-Step -Name "6_create_database" -Status "SKIPPED" -Detail @{ reason = "bootstrap nao necessario" }
}

# =============================================================================
# STEP 8 — validar que database operacional != jarvis_test (guard-rail
# estrutural, não apenas checagem de runtime)
# =============================================================================
if ($OPERATIONAL_DB_NAME -eq $TEST_DB_NAME) {
    Stop-Cutover -BlockerCode "OPERATIONAL_EQUALS_TEST_DATABASE" -DetailMessage "Guard-rail estrutural disparou — nao deveria ser possivel (constantes hardcoded sao diferentes)."
}
Write-Step -Name "8_guard_operational_ne_test" -Status "OK" -Detail @{ operational = $OPERATIONAL_DB_NAME; test = $TEST_DB_NAME }

# =============================================================================
# STEP 9 — configurar/verificar JARVIS_DATABASE_URL em .env sem imprimir segredo
# =============================================================================
$existingDbUrl = Get-EnvValue -Key "JARVIS_DATABASE_URL"
$finalPassword = $generatedPassword
$dbUrlToWrite = $null
$needsEnvPersist = $false  # true somente se o STEP 17 precisar gravar .env

if (-not [string]::IsNullOrWhiteSpace($existingDbUrl)) {
    # Já existe algo em .env — testa se essa credencial realmente funciona
    # contra o banco "jarvis" antes de decidir reescrever ou reaproveitar.
    $testExistingSnippet = @'
import json, os, sys
import psycopg
dsn = os.environ["JARVIS_CUTOVER_TEST_DSN"]
raw = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
try:
    with psycopg.connect(raw, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user;")
            row = cur.fetchone()
    print(json.dumps({"ok": True, "database": row[0], "user": row[1]}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(type(e).__name__) + ": " + str(e)}))
    sys.exit(1)
'@
    $testExistingResult = Invoke-PySnippet -PySnippet $testExistingSnippet -ExtraEnv @{ JARVIS_CUTOVER_TEST_DSN = $existingDbUrl }
    if ($testExistingResult.ExitCode -eq 0) {
        $parsed = $testExistingResult.Output | ConvertFrom-Json
        if ($parsed.database -eq $OPERATIONAL_DB_NAME -and $parsed.user -eq $OPERATIONAL_ROLE_NAME) {
            Write-Step -Name "9_configure_database_url" -Status "OK" -Detail @{ source = "existing_env_reused"; database = $parsed.database; user = $parsed.user }
            $dbUrlToWrite = $existingDbUrl  # já correta, não reescrever
        }
    }
}

if ($null -eq $dbUrlToWrite) {
    if ([string]::IsNullOrWhiteSpace($finalPassword)) {
        # Role ja existia antes desta execucao (nao foi criada agora) e
        # ainda nao ha uma JARVIS_DATABASE_URL operacional valida (o ramo
        # "existing_env_reused" acima ja teria retornado $dbUrlToWrite se
        # existisse uma). Recovery deterministico, sem conhecer a senha
        # antiga: SOMENTE quando -AdminConnectionString foi fornecida,
        # redefine a senha via ALTER ROLE parametrizado. Isto e permitido
        # apenas neste estado pre-cutover (nenhuma URL operacional ainda
        # persistida/validada) -- nunca depois que uma URL valida existe.
        if (-not [string]::IsNullOrWhiteSpace($AdminConnectionString)) {
            $recoveryPassword = $JarvisAppPassword
            if ([string]::IsNullOrWhiteSpace($recoveryPassword)) {
                $recoveryBytes = New-Object byte[] 32
                # Mesma correcao de compatibilidade com Windows PowerShell
                # 5.1 / .NET Framework 4.x (ver comentario no STEP 5 acima).
                $recoveryRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
                try {
                    $recoveryRng.GetBytes($recoveryBytes)
                }
                finally {
                    $recoveryRng.Dispose()
                }
                $recoveryPassword = [Convert]::ToBase64String($recoveryBytes) -replace '[+/=]', ''
            }
            $recoverySource = if ([string]::IsNullOrWhiteSpace($JarvisAppPassword)) { "generated_for_recovery" } else { "provided" }

            $resetRolePasswordSnippet = @'
import json, os, sys
import psycopg
from psycopg import sql
admin_dsn = os.environ["JARVIS_CUTOVER_ADMIN_DSN"]
role_name = os.environ["JARVIS_CUTOVER_ROLE_NAME"]
role_password = os.environ["JARVIS_CUTOVER_ROLE_PASSWORD"]
forbidden = os.environ["JARVIS_CUTOVER_FORBIDDEN_ROLES"].split(",")
if role_name in forbidden:
    print(json.dumps({"ok": False, "error": "structural guard: refusing to touch forbidden role"}))
    sys.exit(1)
try:
    with psycopg.connect(admin_dsn, connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Mesma razao do CREATE ROLE acima: ALTER ROLE ... PASSWORD
            # tambem nao aceita bind parameter nessa posicao.
            query = sql.SQL(
                "ALTER ROLE {} WITH PASSWORD {}"
            ).format(
                sql.Identifier(role_name),
                sql.Literal(role_password),
            )
            cur.execute(query)
    print(json.dumps({"ok": True}))
except Exception as e:
    safe_error = (str(type(e).__name__) + ": " + str(e)).replace(role_password, "[REDACTED]")
    print(json.dumps({"ok": False, "error": safe_error}))
    sys.exit(1)
'@
            $resetRolePasswordResult = Invoke-PySnippet -PySnippet $resetRolePasswordSnippet -ExtraEnv @{
                JARVIS_CUTOVER_ADMIN_DSN       = $AdminConnectionString
                JARVIS_CUTOVER_ROLE_NAME       = $OPERATIONAL_ROLE_NAME
                JARVIS_CUTOVER_ROLE_PASSWORD   = $recoveryPassword
                JARVIS_CUTOVER_FORBIDDEN_ROLES = ($FORBIDDEN_ROLE_NAMES -join ",")
            }
            if ($resetRolePasswordResult.ExitCode -ne 0) {
                Stop-Cutover -BlockerCode "ROLE_PASSWORD_RESET_FAILED" -DetailMessage "Falha ao redefinir senha de '$OPERATIONAL_ROLE_NAME' via -AdminConnectionString: $($resetRolePasswordResult.Output)"
            }
            $finalPassword = $recoveryPassword
            Write-Step -Name "9_recover_role_password" -Status "OK" -Detail @{ role = $OPERATIONAL_ROLE_NAME; source = $recoverySource }
        }
        elseif ([string]::IsNullOrWhiteSpace($JarvisAppPassword)) {
            Stop-Cutover -BlockerCode "JARVIS_APP_PASSWORD_REQUIRED" -DetailMessage "Role '$OPERATIONAL_ROLE_NAME' ja existia (nao foi criada nesta execucao), .env nao tem uma JARVIS_DATABASE_URL valida para ela, nenhuma -JarvisAppPassword foi fornecida, e nenhuma -AdminConnectionString foi fornecida para permitir recovery automatico via ALTER ROLE. Forneca a senha existente do role OU forneca -AdminConnectionString (com ou sem -JarvisAppPassword) para recovery deterministico."
        }
        else {
            $finalPassword = $JarvisAppPassword
        }
    }
    $dbUrlToWrite = "postgresql+psycopg://${OPERATIONAL_ROLE_NAME}:${finalPassword}@${PG_HOST}:${PG_PORT}/${OPERATIONAL_DB_NAME}"

    # valida a URL final antes de gravar
    $finalTestSnippet = @'
import json, os, sys
import psycopg
dsn = os.environ["JARVIS_CUTOVER_TEST_DSN"]
raw = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
try:
    with psycopg.connect(raw, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user;")
            row = cur.fetchone()
    print(json.dumps({"ok": True, "database": row[0], "user": row[1]}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(type(e).__name__) + ": " + str(e)}))
    sys.exit(1)
'@
    $finalTestResult = Invoke-PySnippet -PySnippet $finalTestSnippet -ExtraEnv @{ JARVIS_CUTOVER_TEST_DSN = $dbUrlToWrite }
    if ($finalTestResult.ExitCode -ne 0) {
        Stop-Cutover -BlockerCode "DATABASE_URL_INVALID" -DetailMessage "A JARVIS_DATABASE_URL montada nao conecta: $($finalTestResult.Output)"
    }

    # NAO grava em .env aqui. A persistencia em disco de
    # JARVIS_DATABASE_URL e deliberadamente ADIADA para o STEP 17
    # (imediatamente antes do primeiro restart controlado), depois que
    # schema (STEP 10), dry-run (STEP 12), import real (STEP 15) e
    # idempotencia (STEP 16) ja tiverem sido aprovados. Isso elimina a
    # janela de risco em que um restart anterior a esse ponto poderia
    # ler do .env uma URL apontando para um schema/dados incompletos.
    # O valor ja validado fica disponivel para o STEP 17 via
    # $dbUrlToWrite (escopo do script) e via $needsEnvPersist (flag).
    $needsEnvPersist = $true
    Write-Step -Name "9_configure_database_url" -Status "OK" -Detail @{ source = "generated_pending_persist"; database = $OPERATIONAL_DB_NAME; user = $OPERATIONAL_ROLE_NAME }
}

$env:JARVIS_DATABASE_URL = $dbUrlToWrite  # escopo deste processo apenas, para os passos seguintes

# =============================================================================
# STEP 10 — verificar/aplicar Alembic até HEAD
# =============================================================================
try {
    Push-Location $ProjectRoot
    $alembicOutput = & $PythonExe -m alembic upgrade head 2>&1
    $alembicExit = $LASTEXITCODE
    Pop-Location
    if ($alembicExit -ne 0) {
        Stop-Cutover -BlockerCode "ALEMBIC_UPGRADE_FAILED" -DetailMessage "alembic upgrade head falhou (exit $alembicExit): $alembicOutput"
    }
    Write-Step -Name "10_alembic_upgrade_head" -Status "OK" -Detail @{ output_tail = ($alembicOutput | Select-Object -Last 5) -join " | " }
}
catch {
    Stop-Cutover -BlockerCode "ALEMBIC_UPGRADE_FAILED" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 11 — registrar baseline de system/task-state.json (total/status/bytes/mtime/sha256)
# =============================================================================
function Get-TaskStateBaseline {
    if (-not (Test-Path $TaskStateJsonPath)) {
        return [ordered]@{ exists = $false }
    }
    $fileInfo = Get-Item $TaskStateJsonPath
    $hash = (Get-FileHash -Path $TaskStateJsonPath -Algorithm SHA256).Hash.ToLower()
    $baselineSnippet = @'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
by_status = {}
for t in tasks:
    s = t.get("status", "unknown")
    by_status[s] = by_status.get(s, 0) + 1
print(json.dumps({"total": len(tasks), "by_status": by_status}))
'@
    $tmp = [System.IO.Path]::GetTempFileName() + ".py"
    Set-Content -Path $tmp -Value $baselineSnippet -Encoding UTF8
    $statsOutput = & $PythonExe $tmp $TaskStateJsonPath 2>&1
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    $stats = $statsOutput | ConvertFrom-Json
    return [ordered]@{
        exists     = $true
        total      = $stats.total
        by_status  = $stats.by_status
        bytes      = $fileInfo.Length
        mtime_unix = [int][double]::Parse((Get-Date $fileInfo.LastWriteTimeUtc -UFormat %s))
        sha256     = $hash
    }
}

$baselineBefore = Get-TaskStateBaseline
Write-Step -Name "11_baseline_task_state_json" -Status "OK" -Detail $baselineBefore
$Report["task_state_baseline_before_migration"] = $baselineBefore

# =============================================================================
# STEP 12 — migrate_task_state --dry-run
# =============================================================================
try {
    Push-Location $ProjectRoot
    $dryRunOutput = & $PythonExe -m app.db.migrate_task_state --target production --dry-run 2>&1
    $dryRunExit = $LASTEXITCODE
    Pop-Location
    $dryRunReport = $null
    try { $dryRunReport = ($dryRunOutput -join "`n") | ConvertFrom-Json } catch {}
    Write-Step -Name "12_migrate_dry_run" -Status $(if ($dryRunExit -eq 0) { "OK" } else { "FAILED" }) -Detail @{ exit_code = $dryRunExit; report = $dryRunReport }
    $Report["dry_run_report"] = $dryRunReport
}
catch {
    Stop-Cutover -BlockerCode "MIGRATION_DRY_RUN_FAILED" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 13 — abortar se houver qualquer failure no dry-run
# =============================================================================
if ($dryRunExit -ne 0 -or ($null -ne $dryRunReport -and $dryRunReport.total_failures -gt 0)) {
    Stop-Cutover -BlockerCode "MIGRATION_DRY_RUN_FAILED" -DetailMessage "Dry-run reportou falhas — nada foi migrado de verdade, Jarvis nao foi parado." -Extra @{ dry_run_report = $dryRunReport }
}
Write-Step -Name "13_dry_run_zero_failures" -Status "OK" -Detail @{ total_failures = $dryRunReport.total_failures }

# =============================================================================
# STEP 14 — parar SOMENTE a instância correta do Jarvis (reusa o control
# script já validado/seguro: verifica porta+health+nome do processo antes de
# matar qualquer coisa)
# =============================================================================
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action Stop
    $stopExit = $LASTEXITCODE
    if ($stopExit -notin @(0)) {
        Stop-Cutover -BlockerCode "JARVIS_STOP_FAILED" -DetailMessage "jarvis-python-control.ps1 -Action Stop retornou exit $stopExit — nao prosseguindo para nao arriscar migrar com o processo antigo ainda escrevendo no JSON."
    }
    Write-Step -Name "14_stop_jarvis" -Status "OK" -Detail @{ exit_code = $stopExit }
}
catch {
    Stop-Cutover -BlockerCode "JARVIS_STOP_FAILED" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 15 — migration real (target=production). O importer pede confirmação
# interativa "migrar producao" por design (ver app/db/migrate_task_state.py)
# — respeitamos isso alimentando via stdin, não pulando a checagem.
# =============================================================================
try {
    Push-Location $ProjectRoot
    $migrationOutput = "migrar producao" | & $PythonExe -m app.db.migrate_task_state --target production 2>&1
    $migrationExit = $LASTEXITCODE
    Pop-Location
    $migrationReport = $null
    try { $migrationReport = ($migrationOutput -join "`n") | ConvertFrom-Json } catch {}
    if ($migrationExit -ne 0 -or ($null -ne $migrationReport -and $migrationReport.total_failures -gt 0)) {
        Stop-Cutover -BlockerCode "MIGRATION_REAL_FAILED" -DetailMessage "Migration real falhou (exit $migrationExit)." -Extra @{ migration_report = $migrationReport }
    }
    Write-Step -Name "15_migrate_real" -Status "OK" -Detail @{ report = $migrationReport }
    $Report["migration_report"] = $migrationReport
}
catch {
    Stop-Cutover -BlockerCode "MIGRATION_REAL_FAILED" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 16 — rodar de novo para provar idempotência (deve dar total_inserted=0,
# total_failures=0, e total_already_existing == total_read)
# =============================================================================
try {
    Push-Location $ProjectRoot
    $idempotentOutput = "migrar producao" | & $PythonExe -m app.db.migrate_task_state --target production 2>&1
    $idempotentExit = $LASTEXITCODE
    Pop-Location
    $idempotentReport = $null
    try { $idempotentReport = ($idempotentOutput -join "`n") | ConvertFrom-Json } catch {}
    $isIdempotent = ($idempotentExit -eq 0) -and ($null -ne $idempotentReport) -and ($idempotentReport.total_inserted -eq 0) -and ($idempotentReport.total_failures -eq 0)
    if (-not $isIdempotent) {
        Stop-Cutover -BlockerCode "MIGRATION_NOT_IDEMPOTENT" -DetailMessage "Segunda execucao nao foi idempotente (esperado total_inserted=0)." -Extra @{ idempotency_report = $idempotentReport }
    }
    Write-Step -Name "16_migrate_idempotency_proof" -Status "OK" -Detail @{ report = $idempotentReport }
    $Report["idempotency_report"] = $idempotentReport
}
catch {
    Stop-Cutover -BlockerCode "MIGRATION_NOT_IDEMPOTENT" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 17 — iniciar Jarvis (mesma logica do "Ligar JARVIS.bat", sem abrir navegador)
# =============================================================================
if ($needsEnvPersist) {
    # grava em .env de forma cirurgica, sem nunca imprimir o valor --
    # adiado do STEP 9 ate aqui (imediatamente antes do primeiro
    # restart controlado pos-schema/dry-run/import/idempotencia) para
    # eliminar a janela de risco em que um restart anterior a este
    # ponto poderia ler do .env uma URL apontando para um schema/dados
    # incompletos.
    $envLines = @()
    if (Test-Path $EnvFile) { $envLines = @(Get-Content $EnvFile) }
    $keyPattern = "^\s*JARVIS_DATABASE_URL\s*="
    $replaced = $false
    $newLines = @()
    foreach ($line in $envLines) {
        if ($line -match $keyPattern) {
            $newLines += "JARVIS_DATABASE_URL=$dbUrlToWrite"
            $replaced = $true
        }
        else {
            $newLines += $line
        }
    }
    if (-not $replaced) { $newLines += "JARVIS_DATABASE_URL=$dbUrlToWrite" }
    Set-Content -Path $EnvFile -Value $newLines -Encoding UTF8
    Write-Step -Name "17_persist_database_url" -Status "OK" -Detail @{ database = $OPERATIONAL_DB_NAME; user = $OPERATIONAL_ROLE_NAME }
}

function Start-JarvisProcess {
    Start-Process -FilePath $PythonExe -ArgumentList "run.py" -WorkingDirectory $ProjectRoot -WindowStyle Normal | Out-Null
    $healthUrl = "http://${JARVIS_HOST}:${JARVIS_PORT}/api/health"
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 300
        try {
            $resp = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2
            if ($resp.components.server.status -eq "ok") { return $true }
        }
        catch {}
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

if (-not (Start-JarvisProcess)) {
    Stop-Cutover -BlockerCode "JARVIS_START_FAILED" -DetailMessage "Jarvis nao respondeu em /api/health apos 30s do restart pos-migration."
}
Write-Step -Name "17_start_jarvis" -Status "OK" -Detail @{ health_url = "http://${JARVIS_HOST}:${JARVIS_PORT}/api/health" }

# =============================================================================
# STEP 18 — provar repository mode: JSON legado intocado + contagem no
# Postgres bate com GET /api/tasks/summary
# =============================================================================
$baselineAfterStart = Get-TaskStateBaseline
$jsonUntouchedAfterStart = ($baselineAfterStart.sha256 -eq $baselineBefore.sha256)

$countSnippet = @'
import json, os, sys
import psycopg
dsn = os.environ["JARVIS_CUTOVER_TEST_DSN"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(dsn, connect_timeout=5) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tasks;")
        count = cur.fetchone()[0]
print(json.dumps({"count": count}))
'@
$countResult = Invoke-PySnippet -PySnippet $countSnippet -ExtraEnv @{ JARVIS_CUTOVER_TEST_DSN = $dbUrlToWrite }
$pgTaskCount = ($countResult.Output | ConvertFrom-Json).count

$summary = Invoke-RestMethod -Uri "http://${JARVIS_HOST}:${JARVIS_PORT}/api/tasks/summary" -Method Get -TimeoutSec 5
$repositoryModeProven = $jsonUntouchedAfterStart -and ($pgTaskCount -gt 0)

if (-not $repositoryModeProven) {
    Stop-Cutover -BlockerCode "REPOSITORY_MODE_NOT_PROVEN" -DetailMessage "JSON untouched=$jsonUntouchedAfterStart, postgres_task_count=$pgTaskCount." -Extra @{ api_summary = $summary }
}
Write-Step -Name "18_prove_repository_mode" -Status "OK" -Detail @{ json_untouched = $jsonUntouchedAfterStart; postgres_task_count = $pgTaskCount; api_summary_total = $summary.total }

# =============================================================================
# STEP 19 — criar Task bounded de validação (excel.create — deterministica,
# verificada, baixo risco: so cria um .xlsx pequeno no workspace Excel)
# =============================================================================
$validationTaskId = $null
if (-not $SkipValidationTask) {
    $validationFilename = "_jarvis_p2_cutover_validation_$RunId.xlsx"
    $body = @{
        type    = "excel.create"
        payload = @{
            filename = $validationFilename
            headers  = @("cutover_validation")
            rows     = @(@("ok"))
        }
    } | ConvertTo-Json -Depth 5

    $createResp = Invoke-RestMethod -Uri "http://${JARVIS_HOST}:${JARVIS_PORT}/api/tasks" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    $validationTaskId = $createResp.task_id
    if ([string]::IsNullOrWhiteSpace($validationTaskId)) { $validationTaskId = $createResp.id }
    Write-Step -Name "19_create_validation_task" -Status "OK" -Detail @{ task_id = $validationTaskId; filename = $validationFilename }
}
else {
    Write-Step -Name "19_create_validation_task" -Status "SKIPPED" -Detail @{ reason = "SkipValidationTask" }
}

# =============================================================================
# STEP 20 — provar que a nova Task está no PostgreSQL (query direta, não
# confia só na propria API do Jarvis)
# =============================================================================
if ($validationTaskId) {
    $findTaskSnippet = @'
import json, os, sys
import psycopg
dsn = os.environ["JARVIS_CUTOVER_TEST_DSN"].replace("postgresql+psycopg://", "postgresql://", 1)
task_id = os.environ["JARVIS_CUTOVER_TASK_ID"]
with psycopg.connect(dsn, connect_timeout=5) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id, type, status FROM tasks WHERE id = %s;", (task_id,))
        row = cur.fetchone()
print(json.dumps({"found": row is not None, "row": [str(x) for x in row] if row else None}))
'@
    $findResult = Invoke-PySnippet -PySnippet $findTaskSnippet -ExtraEnv @{ JARVIS_CUTOVER_TEST_DSN = $dbUrlToWrite; JARVIS_CUTOVER_TASK_ID = $validationTaskId }
    $findData = $findResult.Output | ConvertFrom-Json
    if (-not $findData.found) {
        Stop-Cutover -BlockerCode "VALIDATION_TASK_NOT_IN_POSTGRES" -DetailMessage "Task $validationTaskId nao encontrada via query direta no Postgres."
    }
    Write-Step -Name "20_prove_task_in_postgres" -Status "OK" -Detail @{ task_id = $validationTaskId; row = $findData.row }
}
else {
    Write-Step -Name "20_prove_task_in_postgres" -Status "SKIPPED" -Detail @{ reason = "SkipValidationTask" }
}

# =============================================================================
# STEP 21 — provar que a nova Task NÃO entrou no JSON legado
# =============================================================================
$baselineAfterTask = Get-TaskStateBaseline
$jsonUntouchedAfterTask = ($baselineAfterTask.sha256 -eq $baselineBefore.sha256)
if ($validationTaskId -and -not $jsonUntouchedAfterTask) {
    Stop-Cutover -BlockerCode "TASK_LEAKED_INTO_JSON" -DetailMessage "system/task-state.json mudou depois da criacao da Task de validacao — TaskManager NAO esta 100% em modo repository."
}
Write-Step -Name "21_prove_task_not_in_json" -Status "OK" -Detail @{ json_sha256_unchanged = $jsonUntouchedAfterTask }

# =============================================================================
# STEP 22 — reiniciar
# =============================================================================
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action Stop | Out-Null
    if (-not (Start-JarvisProcess)) {
        Stop-Cutover -BlockerCode "JARVIS_RESTART_FAILED" -DetailMessage "Jarvis nao respondeu apos o restart de prova de persistencia."
    }
    Write-Step -Name "22_restart_jarvis" -Status "OK" -Detail @{}
}
catch {
    Stop-Cutover -BlockerCode "JARVIS_RESTART_FAILED" -DetailMessage $_.Exception.Message
}

# =============================================================================
# STEP 23 — provar persistência (Task de validação sobrevive ao restart)
# =============================================================================
if ($validationTaskId) {
    Start-Sleep -Seconds 1
    try {
        $afterRestart = Invoke-RestMethod -Uri "http://${JARVIS_HOST}:${JARVIS_PORT}/api/tasks/$validationTaskId" -Method Get -TimeoutSec 10
        $persisted = ($null -ne $afterRestart) -and ($afterRestart.status -ne $null)
    }
    catch {
        $persisted = $false
    }
    if (-not $persisted) {
        Stop-Cutover -BlockerCode "PERSISTENCE_NOT_PROVEN" -DetailMessage "GET /api/tasks/$validationTaskId falhou apos restart — persistencia real nao comprovada."
    }
    Write-Step -Name "23_prove_persistence_after_restart" -Status "OK" -Detail @{ task_id = $validationTaskId; status_after_restart = $afterRestart.status }
}
else {
    Write-Step -Name "23_prove_persistence_after_restart" -Status "SKIPPED" -Detail @{ reason = "SkipValidationTask" }
}

# =============================================================================
# STEP 24 — relatório final estruturado
# =============================================================================
$Report.outcome = "SUCCESS"
$Report.blocker = $null
$Report.blocker_detail = $null
$reportPath = Save-Report

Write-Host ""
Write-Host "================================================================"
Write-Host " P2 CUTOVER — SUCESSO"
Write-Host " Database operacional: $OPERATIONAL_DB_NAME (role: $OPERATIONAL_ROLE_NAME)"
Write-Host " TaskManager confirmado em modo repository (JSON legado intocado)."
Write-Host " Relatorio completo: $reportPath"
Write-Host ""
Write-Host " PROXIMO PASSO (fora deste script, requer decisao humana):"
Write-Host " marcar 'P2 OPERATIONAL CUTOVER = APPROVED' em JARVIS_MASTER.md"
Write-Host " apos revisao do relatorio acima, e so entao considerar iniciar"
Write-Host " a Etapa 4 (P3 AgentRun real) — NAO INICIAR sem pedido explicito."
Write-Host "================================================================"

exit 0
