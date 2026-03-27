# ============================================================
# MAMUT TRADING BOT - Pruebas Locales para PowerShell
# ============================================================
# Uso: .\test_local.ps1 [-Test <all|imports|config|db|pipeline|scoring>]
# Sin parametros: ejecuta todas las pruebas
# ============================================================

param(
    [ValidateSet("all", "imports", "config", "db", "pipeline", "scoring", "")]
    [string]$Test = "all"
)

$ErrorActionPreference = "Continue"

$script:Passed = 0
$script:Failed = 0
$script:Total  = 0

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "--- $Text ---" -ForegroundColor Yellow
}

function Test-Run {
    param(
        [string]$Name,
        [string]$Script
    )
    $script:Total++
    $result = & $venvPython -c $Script 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [PASS] $Name" -ForegroundColor Green
        if ($result) { Write-Host "         $result" -ForegroundColor DarkGray }
        $script:Passed++
    } else {
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        Write-Host "         $result" -ForegroundColor DarkRed
        $script:Failed++
    }
}

Set-Location $PSScriptRoot

# ------------------------------------------------------------------
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "  [ERROR] Entorno virtual no encontrado." -ForegroundColor Red
    Write-Host "  Ejecuta primero: .\setup.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Header "MAMUT - PRUEBAS LOCALES (PowerShell)"
Write-Host "  Python: $venvPython" -ForegroundColor DarkGray
Write-Host "  Directorio: $PSScriptRoot" -ForegroundColor DarkGray

# ------------------------------------------------------------------
# TEST 1: Importaciones de modulos
# ------------------------------------------------------------------
function Test-Imports {
    Write-Section "IMPORTACIONES DE MODULOS"

    Test-Run "aiohttp" "import aiohttp; print(aiohttp.__version__)"
    Test-Run "websockets" "import websockets; print(websockets.__version__)"
    Test-Run "sqlalchemy" "import sqlalchemy; print(sqlalchemy.__version__)"
    Test-Run "pydantic" "import pydantic; print(pydantic.__version__)"
    Test-Run "loguru" "from loguru import logger; print('ok')"
    Test-Run "httpx" "import httpx; print(httpx.__version__)"
    Test-Run "dotenv" "from dotenv import load_dotenv; print('ok')"

    Write-Section "MODULOS INTERNOS"

    Test-Run "config.settings" "from config.settings import Settings; print('ok')"
    Test-Run "core.event_bus" "from core.event_bus import Event, get_event_bus; print('ok')"
    Test-Run "core.orchestrator" "from core.orchestrator import Orchestrator; print('ok')"
    Test-Run "monitoring.logger" "from monitoring.logger import setup_logger; print('ok')"
    Test-Run "storage.sqlite_store" "from storage.sqlite_store import SQLiteStore; print('ok')"
    Test-Run "storage.models" "from storage.models import Base; print('ok')"
    Test-Run "scoring.score_engine" "from scoring.score_engine import ScoreEngine; print('ok')"
    Test-Run "scoring.decision_mapper" "from scoring.decision_mapper import DecisionMapper; print('ok')"
    Test-Run "signals.signal_engine" "from signals.signal_engine import SignalEngine; print('ok')"
    Test-Run "signals.alert_dispatcher" "from signals.alert_dispatcher import AlertDispatcher; print('ok')"
    Test-Run "filters.trash_filter_engine" "from filters.trash_filter_engine import TrashFilterEngine; print('ok')"
    Test-Run "enrich.token_enricher" "from enrich.token_enricher import TokenEnricher; print('ok')"
    Test-Run "analysis.score_engine import" "from analysis.momentum_engine import MomentumEngine; print('ok')"
}

# ------------------------------------------------------------------
# TEST 2: Configuracion y Settings
# ------------------------------------------------------------------
function Test-Config {
    Write-Section "CONFIGURACION (Settings)"

    Test-Run "Settings carga defaults" @"
from config.settings import Settings
s = Settings()
assert s.pump_ws_url.startswith('wss://'), 'pump_ws_url invalido'
assert s.database_url.startswith('sqlite://'), 'database_url invalido'
assert s.log_level in ('DEBUG','INFO','WARNING','ERROR'), 'log_level invalido'
print(f'DB={s.database_url}  LOG={s.log_level}')
"@

    Test-Run "Settings thresholds validos" @"
from config.settings import Settings
s = Settings()
assert 0 < s.score_threshold_high_potential <= 100
assert 0 < s.score_threshold_medium_potential <= 100
assert s.score_threshold_medium_potential < s.score_threshold_high_potential
print(f'high={s.score_threshold_high_potential}  medium={s.score_threshold_medium_potential}')
"@

    Test-Run "Thresholds de riesgo validos" @"
from config.settings import Settings
s = Settings()
assert 0 < s.authority_risk_max <= 100
assert 0 < s.creator_risk_max <= 100
assert 0 < s.concentration_max <= 100
print(f'authority={s.authority_risk_max}  creator={s.creator_risk_max}  conc={s.concentration_max}')
"@
}

# ------------------------------------------------------------------
# TEST 3: Base de Datos
# ------------------------------------------------------------------
function Test-Database {
    Write-Section "BASE DE DATOS (SQLite)"

    Test-Run "Crear SQLiteStore" @"
import os, tempfile
from config.settings import Settings
from storage.sqlite_store import SQLiteStore
s = Settings()
s.database_url = 'sqlite:///./test_mamut_temp.db'
store = SQLiteStore(s)
import asyncio
asyncio.run(store.initialize())
print('store inicializado OK')
"@

    Test-Run "Guardar y recuperar token" @"
import asyncio, os
from config.settings import Settings
from storage.sqlite_store import SQLiteStore
from storage.models import TokenRecord

async def run():
    s = Settings()
    s.database_url = 'sqlite:///./test_mamut_temp.db'
    store = SQLiteStore(s)
    await store.initialize()
    token = TokenRecord(
        mint='TestMint111111111111111111111111111111111111',
        symbol='TEST',
        name='Test Token',
        risk_level='LOW_RISK',
        score=75.0
    )
    await store.save_token(token)
    retrieved = await store.get_token('TestMint111111111111111111111111111111111111')
    assert retrieved is not None
    assert retrieved.symbol == 'TEST'
    assert retrieved.score == 75.0
    print(f'Token guardado y recuperado: {retrieved.symbol} score={retrieved.score}')

asyncio.run(run())
"@

    Test-Run "Limpiar DB temporal" @"
import os
if os.path.exists('test_mamut_temp.db'):
    os.remove('test_mamut_temp.db')
    print('DB temporal eliminada')
else:
    print('No habia DB temporal')
"@
}

# ------------------------------------------------------------------
# TEST 4: Pipeline de Scoring
# ------------------------------------------------------------------
function Test-Pipeline {
    Write-Section "PIPELINE - EVENTOS Y BUS"

    Test-Run "Event Bus: emitir y suscribir" @"
import asyncio
from datetime import datetime
from core.event_bus import Event, get_event_bus

received = []

async def run():
    bus = get_event_bus()
    await bus.start()
    
    async def handler(event):
        received.append(event.event_type)
    
    bus.subscribe('TEST_EVENT', handler)
    await bus.emit_sync(Event(event_type='TEST_EVENT', data={'key': 'value'}, timestamp=datetime.utcnow(), source='test'))
    await bus.stop()
    assert 'TEST_EVENT' in received, f'Evento no recibido: {received}'
    print(f'Evento recibido correctamente: {received}')

asyncio.run(run())
"@

    Test-Run "TokenLockManager: adquirir y liberar lock" @"
from core.token_lock_manager import TokenLockManager

mgr = TokenLockManager()
mint = 'TestMint123'
acquired = mgr.lock_token(mint)
assert acquired, 'No se pudo adquirir lock'
double = mgr.lock_token(mint)
assert not double, 'Lock duplicado no deberia adquirirse'
mgr.unlock_token(mint)
reacquired = mgr.lock_token(mint)
assert reacquired, 'No se pudo readquirir lock tras liberacion'
mgr.unlock_token(mint)
print('Lock adquirido, bloqueado, liberado y readquirido correctamente')
"@

    Test-Run "SignalDeduper: deduplicacion" @"
from core.signal_deduper import SignalDeduper

deduper = SignalDeduper()
mint = 'TestMint456'
first  = deduper.is_duplicate(mint, 'SIGNAL_EARLY', 75.0)
second = deduper.is_duplicate(mint, 'SIGNAL_EARLY', 75.0)
assert not first,  'Primera vez no deberia ser duplicado'
assert second,     'Segunda vez deberia ser duplicado'
print(f'Deduplicacion OK: first={first} second={second}')
"@
}

# ------------------------------------------------------------------
# TEST 5: Motor de Scoring
# ------------------------------------------------------------------
function Test-Scoring {
    Write-Section "MOTOR DE SCORING"

    Test-Run "ScoreEngine: token de alta calidad" @"
from scoring.score_engine import ScoreEngine

engine = ScoreEngine()
event_data = {
    'mint': 'TestMint789',
    'symbol': 'GOOD',
    'authority_risk': 10.0,
    'creator_risk': 15.0,
    'concentration_risk': 20.0,
    'filter_results': {
        'checks': {
            'authority': {'score': 90.0},
            'creator': {'score': 85.0},
            'concentration': {'score': 80.0}
        }
    }
}
result = engine.calculate(event_data)
assert result['score'] > 50, f'Score esperado > 50, obtenido: {result[\"score\"]}'
print(f'Score calculado: {result[\"score\"]:.1f}  riesgo={result.get(\"risk_level\")}')
"@

    Test-Run "ScoreEngine: token de alto riesgo" @"
from scoring.score_engine import ScoreEngine

engine = ScoreEngine()
event_data = {
    'mint': 'RiskyMintABC',
    'symbol': 'RISKY',
    'authority_risk': 90.0,
    'creator_risk': 85.0,
    'concentration_risk': 95.0,
    'filter_results': {
        'checks': {
            'authority': {'score': 10.0},
            'creator': {'score': 15.0},
            'concentration': {'score': 5.0}
        }
    }
}
result = engine.calculate(event_data)
assert result['score'] < 50, f'Score esperado < 50, obtenido: {result[\"score\"]}'
print(f'Score calculado: {result[\"score\"]:.1f}  riesgo={result.get(\"risk_level\")}')
"@

    Test-Run "DecisionMapper: mapeo de decisiones" @"
from config.settings import Settings
from scoring.decision_mapper import DecisionMapper

dm = DecisionMapper(Settings())
# HIGH_POTENTIAL
high = dm.map({'score': 80.0, 'risk_level': 'LOW_RISK', 'mint': 'A', 'symbol': 'A'})
assert high['decision'] in ('SIGNAL_EARLY', 'SIGNAL', 'BUY'), f'Decision inesperada: {high[\"decision\"]}'
# SKIP
low  = dm.map({'score': 20.0, 'risk_level': 'HIGH_RISK', 'mint': 'B', 'symbol': 'B'})
assert low['decision']  in ('SKIP', 'REJECT', 'IGNORE'), f'Decision inesperada: {low[\"decision\"]}'
print(f'high={high[\"decision\"]}  low={low[\"decision\"]}')
"@
}

# ------------------------------------------------------------------
# Resumen
# ------------------------------------------------------------------
function Show-Summary {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  RESUMEN DE PRUEBAS" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Total : $($script:Total)" -ForegroundColor White
    Write-Host "  Passed: $($script:Passed)" -ForegroundColor Green
    Write-Host "  Failed: $($script:Failed)" -ForegroundColor $(if ($script:Failed -gt 0) { "Red" } else { "Green" })
    Write-Host ""

    if ($script:Failed -eq 0) {
        Write-Host "  Todas las pruebas PASARON correctamente." -ForegroundColor Green
    } else {
        Write-Host "  Algunas pruebas FALLARON. Revisa los errores anteriores." -ForegroundColor Red
        Write-Host "  Asegurate de haber ejecutado .\setup.ps1 primero." -ForegroundColor Yellow
    }
    Write-Host ""
}

# ------------------------------------------------------------------
# Dispatch
# ------------------------------------------------------------------
switch ($Test) {
    "imports"  { Test-Imports;  Show-Summary }
    "config"   { Test-Config;   Show-Summary }
    "db"       { Test-Database; Show-Summary }
    "pipeline" { Test-Pipeline; Show-Summary }
    "scoring"  { Test-Scoring;  Show-Summary }
    default {
        # all
        Test-Imports
        Test-Config
        Test-Database
        Test-Pipeline
        Test-Scoring
        Show-Summary
    }
}

exit $script:Failed
