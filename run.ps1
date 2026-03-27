# ============================================================
# MAMUT TRADING BOT - Script Principal para PowerShell
# ============================================================
# Uso: .\run.ps1 [-Mode <bot|monitor|db|signals|logs|setup>]
# Sin parametros: muestra menu interactivo
# ============================================================

param(
    [ValidateSet("bot", "monitor", "db", "signals", "logs", "setup", "")]
    [string]$Mode = ""
)

$ErrorActionPreference = "Stop"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-MenuOption {
    param([string]$Key, [string]$Text)
    Write-Host "  [$Key] $Text" -ForegroundColor White
}

Set-Location $PSScriptRoot

# ------------------------------------------------------------------
# Verificar que el entorno virtual existe
# ------------------------------------------------------------------
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "  [ERROR] Entorno virtual no encontrado." -ForegroundColor Red
    Write-Host "  Ejecuta primero: .\setup.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ------------------------------------------------------------------
# Funciones para cada modo
# ------------------------------------------------------------------

function Start-Bot {
    Write-Header "MAMUT BOT - INICIANDO"
    Write-Host "  Presiona Ctrl+C para detener el bot." -ForegroundColor DarkYellow
    Write-Host ""
    & $venvPython main.py
}

function Start-Monitor {
    Write-Header "MAMUT MONITOR EN VIVO"
    Write-Host "  Presiona Ctrl+C para salir." -ForegroundColor DarkYellow
    Write-Host ""
    & $venvPython monitor.py
}

function Check-Database {
    Write-Header "MAMUT - REVISAR BASE DE DATOS"
    Write-Host ""
    & $venvPython check_db.py
    Write-Host ""
    Write-Host "Presiona Enter para volver al menu..." -ForegroundColor DarkGray
    $null = Read-Host
}

function Check-Signals {
    Write-Header "MAMUT - REVISAR SEÑALES"
    Write-Host ""
    & $venvPython check_signals.py
    Write-Host ""
    Write-Host "Presiona Enter para volver al menu..." -ForegroundColor DarkGray
    $null = Read-Host
}

function Watch-Logs {
    Write-Header "MAMUT - MONITOR DE LOGS"
    Write-Host "  Presiona Ctrl+C para salir." -ForegroundColor DarkYellow
    Write-Host ""
    & $venvPython watch_logs.py
}

function Run-Setup {
    Write-Header "MAMUT - SETUP"
    & "$PSScriptRoot\setup.ps1"
}

function Show-Menu {
    while ($true) {
        Write-Header "MAMUT TRADING BOT - MENU PRINCIPAL"
        Write-Host ""
        Write-MenuOption "1" "Iniciar el Bot (main.py)"
        Write-MenuOption "2" "Monitor en Vivo (monitor.py)"
        Write-MenuOption "3" "Revisar Base de Datos (check_db.py)"
        Write-MenuOption "4" "Revisar Señales (check_signals.py)"
        Write-MenuOption "5" "Ver Logs en Tiempo Real (watch_logs.py)"
        Write-MenuOption "6" "Re-ejecutar Setup"
        Write-MenuOption "Q" "Salir"
        Write-Host ""

        $choice = Read-Host "  Elige una opcion"

        switch ($choice.ToUpper()) {
            "1" { Start-Bot }
            "2" { Start-Monitor }
            "3" { Check-Database }
            "4" { Check-Signals }
            "5" { Watch-Logs }
            "6" { Run-Setup }
            "Q" {
                Write-Host ""
                Write-Host "  Hasta luego!" -ForegroundColor Cyan
                Write-Host ""
                exit 0
            }
            default {
                Write-Host "  Opcion no valida. Intenta de nuevo." -ForegroundColor Red
            }
        }
    }
}

# ------------------------------------------------------------------
# Dispatch por modo
# ------------------------------------------------------------------
switch ($Mode) {
    "bot"     { Start-Bot }
    "monitor" { Start-Monitor }
    "db"      { Check-Database }
    "signals" { Check-Signals }
    "logs"    { Watch-Logs }
    "setup"   { Run-Setup }
    default   { Show-Menu }
}
