# 🦣 MAMUT Trading Bot — Resumen Completo del Sistema

> **Estado:** ✅ Operacional | **Blockchain:** Solana | **Última actualización:** 2026-03-26

---

## ¿Qué hace el bot?

Mamut es un motor de análisis y generación de señales de trading para tokens nuevos en la blockchain de **Solana**. Detecta en tiempo real los tokens lanzados en **Pump.fun**, los analiza en múltiples dimensiones de riesgo y calidad, y genera **señales accionables** con nivel de confianza para potenciales oportunidades de entrada temprana.

El bot **no ejecuta órdenes de compra/venta directamente**; su función es detectar, filtrar, puntuar y alertar sobre tokens con potencial, enviando señales a canales externos (Discord / Telegram vía webhook).

---

## Arquitectura General

El sistema sigue una arquitectura de **pipeline basado en eventos** (Event Bus). Cada etapa produce un evento que dispara la siguiente, de forma desacoplada y asíncrona.

```
[Pump.fun WebSocket]
        │
        ▼
  1. DISCOVERY ─────────────► TokenDiscovered
        │
        ▼
  2. ENRICHMENT ────────────► TokenEnriched
        │
        ▼
  3. FILTERING ─────────────► TokenPassed / TokenRejected
        │
        ▼
  4. SCORING ───────────────► ScoreCalculated
        │
        ▼
  5. DECISION ──────────────► DecisionMade
        │
        ▼
  6. SIGNAL GENERATION ─────► SignalGenerated
        │
        ▼
  7. ALERT DISPATCH ────────► AlertDispatched
                              (Discord / Telegram / SQLite)
```

Paralelamente, existe un pipeline secundario de **validación en Raydium** para confirmar la migración de tokens a exchanges descentralizados.

---

## Pipeline Principal — Detalle por Etapa

### 1. 🔍 DISCOVERY — Detección de Tokens Nuevos
**Módulos:** `discovery/pump_listener.py`, `discovery/pump_event_parser.py`, `discovery/token_registry.py`, `discovery/launch_tracker.py`

- Establece conexión **WebSocket** con `pumpportal.fun/api/data` mediante el método `subscribeNewToken`.
- Gestiona **reconexión automática con backoff exponencial** (5 s → 10 s → 20 s → ... máximo 60 s, hasta 10 intentos).
- Por cada mensaje recibido, el `PumpEventParser` extrae los campos clave:
  - `mint` (dirección del token)
  - `name`, `symbol`
  - `creator` (wallet del creador)
  - `signature` (tx de creación)
  - `initial_sol` (SOL invertido en la compra inicial, desde lamports)
  - `market_cap_sol`, `uri` (metadata)
- Si el evento es válido, emite el evento `TokenDiscovered` al bus de eventos.

**Evento emitido:** `TokenDiscovered`

---

### 2. 🧬 ENRICHMENT — Enriquecimiento On-Chain y de Metadata
**Módulos:** `enrich/token_enricher.py`, `enrich/metadata_analyzer.py`, `enrich/creator_profiler.py`, `enrich/holder_analyzer.py`

El `TokenEnricher` realiza **tres consultas paralelas** para cada token:

| Consulta | API | Datos obtenidos |
|----------|-----|-----------------|
| `getTokenSupply` | Solana RPC (`api.mainnet-beta.solana.com`) | `decimals`, `total_supply` |
| `getAccountInfo` | Solana RPC | `mint_authority`, `freeze_authority`, `owner`, `owner_renounced` |
| URI metadata | IPFS / Arweave / HTTP | `description`, `website`, `twitter`, `telegram`, `image` |

Con los datos obtenidos, el `MetadataAnalyzer` calcula:
- **`metadata_score`** (0–100): calidad de la metadata del token (nombre, descripción, sociales).
- **`metadata_risk_flags`**: lista de banderas de riesgo (ej. `"no_description"`, `"no_socials"`).
- **`has_website`**, **`has_twitter`**, **`has_telegram`**, **`social_count`**.

El `CreatorProfiler` consulta el historial del creador en la base de datos local:
- Tokens lanzados previamente, tasa de éxito/fracaso, antigüedad de la wallet.

El `HolderAnalyzer` evalúa la distribución inicial de holders:
- Concentración del top 1/5/10 holders, porcentaje del creador, wallets fresh, snipers detectados.

**Evento emitido:** `TokenEnriched`

---

### 3. 🚦 FILTERING — Filtrado Multi-Capa
**Módulos:** `filters/trash_filter_engine.py`, `filters/honeypot_detector.py`, `filters/authority_checker.py`, `filters/concentration_checker.py`, `filters/creator_risk_checker.py`, `filters/wallet_cluster_checker.py`

El `TrashFilterEngine` ejecuta **5 checks de riesgo** en cascada:

#### 3a. Authority Risk (Riesgo de Autoridades)
| Factor | Penalización |
|--------|-------------|
| Freeze authority activa | +45 puntos de riesgo |
| Mint authority activa | +35 puntos de riesgo |
| Owner no renounced | +15 puntos de riesgo |

#### 3b. Creator Risk (Riesgo del Creador)
| Factor | Puntuación base |
|--------|-----------------|
| Creador blacklisted | 95 (rechazo automático) |
| Creador trusted | 15 (favorecido) |
| Sin historial conocido | 45 |
| Wallet < 7 días | +15 puntos de riesgo |
| Wallet < 30 días | +8 puntos de riesgo |
| Tasa de éxito < 10% (≥5 tokens) | +20 puntos de riesgo |

#### 3c. Concentration Risk (Riesgo de Concentración)
| Porcentaje del creador | Riesgo |
|-----------------------|--------|
| > 90% del supply | 95 (riesgo crítico) |
| > 70% | 80 |
| > 50% | 65 |
| < 20% | 25 (bajo riesgo) |
| Más de 100 holders | -15 (beneficio) |

#### 3d. Metadata Risk (Riesgo de Metadata)
- Si metadata no está disponible aún → riesgo moderado (35), no penalización severa.
- Escala basada en `metadata_score`: `max(5, min(85, 70 - score * 0.6))`.
- Sin sociales detectadas → +5; con ≥2 sociales → -8.

#### 3e. Honeypot Detection (Detección de Honeypot)
Analiza señales de tokens tipo honeypot en Solana:
- Freeze/mint authority activas.
- Supply inválido o extremadamente bajo.
- Alta tasa de fracaso del creador.
- Alta concentración en top holders.
- Wallets cluster sospechosas.

**Criterio de pase:** `aggregate_risk_score ≤ 75` (configurable en `TRASH_FILTER_THRESHOLDS`).

Los **risk scores individuales** (`authority_risk`, `creator_risk`, `concentration_risk`) se almacenan como campos de primer nivel en el evento `TokenPassed`.

**Eventos emitidos:** `TokenPassed` / `TokenRejected`

---

### 4. 📊 SCORING — Puntuación Final
**Módulo:** `scoring/score_engine.py`

El `ScoreEngine` calcula la puntuación final del token (0–100) partiendo de una **base de 62 puntos** y aplicando ajustes:

| Factor | Ajuste |
|--------|--------|
| `metadata_score ≥ 80` | +10 |
| `metadata_score ≥ 60` | +7 |
| `metadata_score ≥ 40` | +3 |
| `social_count ≥ 3` | +7 |
| `social_count == 2` | +4 |
| `social_count == 1` | +2 |
| Market cap 15–250 SOL | +6 |
| Market cap 5–15 SOL | +3 |
| Market cap > 500 SOL | -3 |
| `aggregate_risk_score` | `- risk * 0.38` |
| `authority_risk ≥ 80` | -6 adicionales |
| `creator_risk ≥ 80` | -5 adicionales |
| `concentration_risk ≥ 85` | -5 adicionales |
| `honeypot_risk ≥ 80` | -8 adicionales |

La **confianza** se calcula como:
```
confidence = (final_score/100) * 0.5
           + (cleanliness/100) * 0.3
           + data_completeness * 0.2
```

**Evento emitido:** `ScoreCalculated`

---

### 5. 🧭 DECISION — Toma de Decisión
**Módulo:** `scoring/decision_mapper.py`

El `DecisionMapper` mapea el score y confianza a una de 4 decisiones:

| Decisión | Condición | Etiqueta | Color |
|----------|-----------|----------|-------|
| `SIGNAL_EARLY` | score ≥ 70 **AND** confidence ≥ 0.65 **AND** aggregate_risk ≤ 45 | HIGH_POTENTIAL | 🟢 Verde |
| `MONITOR` | score ≥ 50 **AND** confidence ≥ 0.45 **AND** aggregate_risk ≤ 65 | MEDIUM_POTENTIAL | 🟡 Amarillo |
| `WARN` | score ≥ 30 | LOW_POTENTIAL | 🟠 Naranja |
| `REJECT` | score < 30 | TRASH | 🔴 Rojo |

Los umbrales son configurables en `config/settings.py`:
```
score_threshold_high_potential = 70.0
score_threshold_medium_potential = 50.0
score_threshold_low_potential = 30.0
```

**Evento emitido:** `DecisionMade`

---

### 6. 📡 SIGNAL GENERATION — Generación de Señales
**Módulos:** `signals/signal_engine.py`, `signals/signal_formatter.py`

Para tokens con decisión `SIGNAL_EARLY`, el `SignalEngine` genera un objeto `SignalData` que incluye:

| Campo | Descripción |
|-------|-------------|
| `signal_id` | UUID único (`SIGNAL-{hex[:12]}`) |
| `signal_type` | `EARLY` |
| `mint` | Dirección del token |
| `symbol` | Símbolo |
| `score` | Puntuación final (0–100) |
| `confidence` | Nivel de confianza (0–1) |
| `risk_level` | Nivel de riesgo (`HIGH_POTENTIAL`, etc.) |
| `reason` | Texto descriptivo del razonamiento |
| `metadata` | Datos completos del token + scores |
| `timestamp` | Fecha/hora UTC |

El `SignalFormatter` puede formatear la señal en:
- **JSON**: para almacenamiento y APIs.
- **Texto plano**: formato legible con tabla de scores por componente.
- **Webhook**: payload para Discord/Telegram.

**Evento emitido:** `SignalGenerated`

---

### 7. 🚨 ALERT DISPATCH — Despacho de Alertas
**Módulo:** `signals/alert_dispatcher.py`

El `AlertDispatcher` distribuye las señales por múltiples canales:

| Canal | Configuración |
|-------|---------------|
| **Webhook** (Discord / Telegram) | Variable `WEBHOOK_URL` en `.env` |
| **SQLite** | Base de datos local `mamut.db` |

- Si `ALERT_ENABLED=false`, las alertas se suprimen.
- Reintentos automáticos en caso de fallo de red (`alert_retry_count`).

**Evento emitido:** `AlertDispatched`

---

## Pipeline Secundario — Validación en Raydium

**Módulos:** `validation/raydium_listener.py`, `validation/raydium_pool_validator.py`, `validation/market_confirmation_engine.py`, `analysis/migration_tracker.py`

Para tokens que migran de Pump.fun a Raydium (exchange descentralizado principal de Solana), el bot ejecuta:

1. **Raydium Listener**: Escucha el WebSocket de Raydium para detectar nuevas pools.
2. **Raydium Pool Validator**: Valida que la pool:
   - Use un `program_id` oficial de Raydium AMM.
   - Tenga edad aceptable (configurable, máximo 30 min).
   - Tenga suficiente liquidez (mínimo 10 SOL por defecto).
   - Use SOL como token de cotización (`So11111111111111...`).
3. **Market Confirmation Engine**: Confirma condiciones de mercado post-validación:
   - Calidad de liquidez (baja/buena/fuerte según SOL disponibles).
   - Score de validación compuesto.
   - Stage del mercado (`UNCONFIRMED` → `CONFIRMED`).
4. **Migration Tracker**: Registra el estado de migración (`PUMP_FUN_ONLY` → `MIGRATED_TO_RAYDIUM`).

---

## Módulos de Análisis Avanzado (en desarrollo)

**Módulos:** `analysis/flow_analyzer.py`, `analysis/buyer_quality_analyzer.py`, `analysis/velocity_analyzer.py`, `analysis/momentum_engine.py`

| Módulo | Función |
|--------|---------|
| `FlowAnalyzer` | Analiza volumen y momentum de trading via DexScreener / Solscan |
| `BuyerQualityAnalyzer` | Evalúa calidad de compradores iniciales (patrones, wallets tipo bot) |
| `VelocityAnalyzer` | Calcula velocidad de cambio de precio y volumen |
| `MomentumEngine` | Analiza momentum general del token (stub, en desarrollo) |

---

## Infraestructura Core

**Módulos:** `core/orchestrator.py`, `core/event_bus.py`, `core/token_lock_manager.py`, `core/signal_deduper.py`, `core/state_manager.py`

| Componente | Función |
|------------|---------|
| **Orchestrator** | Coordina el arranque y apagado de todos los componentes |
| **Event Bus** | Bus de eventos asíncrono; desacopla emisores y suscriptores |
| **Token Lock Manager** | Evita el procesamiento concurrente del mismo token (max 100 locks simultáneos, timeout 300 s) |
| **Signal Deduper** | Elimina señales duplicadas en ventana de 60 s, excepto si el score cambia >5 puntos |
| **State Manager** | Gestiona el estado global de la aplicación |

---

## Persistencia y Almacenamiento

**Módulos:** `storage/sqlite_store.py`, `storage/models.py`

Base de datos **SQLite** (`mamut.db`) con tablas para:
- Tokens descubiertos, enriquecidos y analizados.
- Perfiles de creadores (historial, tokens lanzados, tasa de éxito).
- Señales generadas.
- Estadísticas del sistema.

---

## Configuración

Archivo `.env` (basado en `.env.example`):

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `PUMP_WS_URL` | `wss://pumpportal.fun/api/data` | WebSocket de Pump.fun |
| `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | RPC de Solana |
| `WEBHOOK_URL` | — | URL de Discord/Telegram webhook |
| `ALERT_ENABLED` | `true` | Activar/desactivar alertas |
| `SCORE_THRESHOLD_HIGH_POTENTIAL` | `70.0` | Umbral para señal early |
| `SCORE_THRESHOLD_MEDIUM_POTENTIAL` | `50.0` | Umbral para monitor |
| `DATABASE_URL` | `sqlite:///./mamut.db` | Base de datos |
| `LOG_LEVEL` | `INFO` | Nivel de logging |

---

## Observabilidad

**Módulo:** `monitoring/logger.py`

- Logging estructurado con **Loguru** a consola y archivo (`logs/mamut.log`).
- Rotación de logs automática (500 MB, retención 7 días).
- Scripts de utilidad: `watch_logs.py`, `monitor.py`, `check_db.py`, `check_signals.py`.
- Cada componente expone `get_stats()` con métricas de operación (tokens procesados, errores, tasas de éxito).

---

## Flujo de Datos Completo (Resumen Visual)

```
Pump.fun WebSocket
      │
      │ ─► TokenDiscovered {mint, symbol, creator, initial_sol, ...}
      │
      ▼
TokenEnricher (Solana RPC + URI)
      │
      │ ─► TokenEnriched {+ decimals, supply, authorities, metadata_score, socials}
      │
      ▼
TrashFilterEngine
      ├── Authority Risk Check
      ├── Creator Risk Check (DB lookup)
      ├── Concentration Risk Check
      ├── Metadata Risk Check
      └── Honeypot Detection
      │
      │ ─► TokenPassed {authority_risk, creator_risk, concentration_risk, aggregate_risk}
      │    o TokenRejected {reason}
      │
      ▼
ScoreEngine
      │
      │ ─► ScoreCalculated {final_score: 0-100, confidence: 0-1, breakdown}
      │
      ▼
DecisionMapper
      │
      │ ─► DecisionMade {SIGNAL_EARLY | MONITOR | WARN | REJECT}
      │
      ▼
SignalEngine (solo si SIGNAL_EARLY)
      │
      │ ─► SignalGenerated {signal_id, score, confidence, risk_level, reason}
      │
      ▼
AlertDispatcher
      ├── Webhook (Discord/Telegram)
      └── SQLite DB
      │
      └► AlertDispatched ✅
```

---

## Próximos Pasos Planificados

- [ ] Activar webhooks Discord/Telegram con URLs configuradas
- [ ] Integrar análisis de money flows (FlowAnalyzer completo)
- [ ] Completar análisis de calidad de buyers (BuyerQualityAnalyzer)
- [ ] Validación activa de pools en Raydium en pipeline principal
- [ ] Implementar predicciones con ML
- [ ] Dashboard en tiempo real

---

*Autor: mamutrading520-coder | Engine: Mamut v1.0*
