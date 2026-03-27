# ============================================================
# MAMUT TRADING BOT - Setup Script para PowerShell (Windows)
# ============================================================
# Uso: .\setup.ps1
# Descripcion: Configura el entorno completo de Mamut localmente
# ============================================================

param(
    [switch]$Force   # Fuerza reinstalacion si el entorno ya existe
)

$ErrorActionPreference = "Stop"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host ">> $Text" -ForegroundColor Yellow
}

function Write-OK {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [WARN] $Text" -ForegroundColor DarkYellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "  [ERROR] $Text" -ForegroundColor Red
}

# ------------------------------------------------------------------
Write-Header "MAMUT TRADING BOT - SETUP LOCAL"
Write-Host "  Entorno: Windows PowerShell" -ForegroundColor White
Write-Host "  Directorio: $PSScriptRoot" -ForegroundColor White

Set-Location $PSScriptRoot

# ------------------------------------------------------------------
Write-Step "1/6  Verificando Python..."

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 9) {
                $pythonCmd = $cmd
                Write-OK "Encontrado: $ver"
                break
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Fail "Python 3.9+ no encontrado. Instala Python desde https://www.python.org/downloads/"
    exit 1
}

# ------------------------------------------------------------------
Write-Step "2/6  Creando entorno virtual (.venv)..."

$venvPath = Join-Path $PSScriptRoot ".venv"

if (Test-Path $venvPath) {
    if ($Force) {
        Write-Warn "Eliminando entorno virtual anterior (--Force)..."
        Remove-Item -Recurse -Force $venvPath
    } else {
        Write-OK "Entorno virtual ya existe. Usa -Force para recrearlo."
    }
}

if (-not (Test-Path $venvPath)) {
    & $pythonCmd -m venv .venv
    Write-OK "Entorno virtual creado en .venv"
}

# ------------------------------------------------------------------
Write-Step "3/6  Instalando dependencias..."

$pip = Join-Path $venvPath "Scripts\pip.exe"
if (-not (Test-Path $pip)) {
    Write-Fail "No se encontro pip en el entorno virtual."
    exit 1
}

& $pip install --upgrade pip --quiet
& $pip install -r requirements.txt --quiet
Write-OK "Dependencias instaladas desde requirements.txt"

# ------------------------------------------------------------------
Write-Step "4/6  Creando directorios necesarios..."

$dirs = @("logs", "data")
foreach ($d in $dirs) {
    $fullPath = Join-Path $PSScriptRoot $d
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath | Out-Null
        Write-OK "Creado: $d\"
    } else {
        Write-OK "Ya existe: $d\"
    }
}

# ------------------------------------------------------------------
Write-Step "5/6  Configurando archivo .env..."

$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"

if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-OK "Creado .env desde .env.example"
        Write-Warn "Edita .env con tus claves RPC antes de ejecutar el bot."
    } else {
        # Crear .env con valores por defecto
        @"
PUMP_WS_URL=wss://pumpportal.fun/api/data
PUMP_RECONNECT_DELAY=5
PUMP_MAX_RETRIES=10
RAYDIUM_API_URL=https://api.raydium.io/v2/sdk/liquidity/mainnet.json
RAYDIUM_POOL_TIMEOUT=30
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
DATABASE_URL=sqlite:///./mamut.db
LOG_LEVEL=INFO
WEBHOOK_URL=
ALERT_ENABLED=false
"@ | Set-Content $envFile -Encoding UTF8
        Write-OK "Creado .env con configuracion por defecto"
        Write-Warn "Edita .env con tus claves RPC antes de ejecutar el bot."
    }
} else {
    Write-OK ".env ya existe. No se sobreescribe."
}

# ------------------------------------------------------------------
Write-Step "6/6  Verificando instalacion..."

$python = Join-Path $venvPath "Scripts\python.exe"

$checkResult = & $python -c "
import importlib, sys
deps = ['aiohttp', 'websockets', 'sqlalchemy', 'pydantic', 'dotenv', 'httpx', 'loguru']
missing = [d for d in deps if importlib.util.find_spec(d) is None]
if missing:
    print('MISSING:' + ','.join(missing))
    sys.exit(1)
print('OK')
" 2>&1

if ($checkResult -match "^OK") {
    Write-OK "Todas las dependencias verificadas correctamente"
} elseif ($checkResult -match "MISSING:(.+)") {
    Write-Fail "Dependencias faltantes: $($Matches[1])"
    exit 1
} else {
    Write-Warn "Verificacion con advertencias: $checkResult"
}

# ------------------------------------------------------------------
Write-Header "SETUP COMPLETADO"
Write-Host ""
Write-Host "  Para ejecutar Mamut usa:" -ForegroundColor White
Write-Host "    .\run.ps1                  -> Menu principal" -ForegroundColor Green
Write-Host "    .\run.ps1 -Mode bot        -> Iniciar el bot" -ForegroundColor Green
Write-Host "    .\run.ps1 -Mode monitor    -> Monitor en vivo" -ForegroundColor Green
Write-Host "    .\run.ps1 -Mode db         -> Revisar base de datos" -ForegroundColor Green
Write-Host "    .\test_local.ps1           -> Pruebas locales" -ForegroundColor Green
Write-Host ""
Write-Host "  NOTA: Edita .env con tus valores antes de iniciar el bot." -ForegroundColor DarkYellow
Write-Host ""
