# ?? MAMUT PROJECT PROMPT

## Descripción General
Mamut es un bot de trading automático que detecta tokens nuevos en tiempo real en la blockchain de Solana, los analiza y genera señales de trading basadas en múltiples factores.

## Objetivo Principal
Identificar tokens con alto potencial de ganancia detectando patrones, analizando creadores y validando en exchanges.

## Fases del Pipeline

### 1. DISCOVERY (Detección)
- Escucha WebSocket de Pump.fun
- Detecta nuevos tokens (mint, symbol, creator)
- Parsea eventos en tiempo real
- **Evento:** \TokenDiscovered\

### 2. ENRICHMENT (Enriquecimiento)
- Obtiene metadata on-chain (token account)
- Descarga URI metadata (imagen, descripción)
- Analiza perfil del creador
- Calcula scores: authority_score, creator_score
- **Eventos:** \TokenEnriched\, \CreatorProfiled\

### 3. FILTERING (Filtrado)
- Verifica thresholds:
  - Authority score >= 35
  - Creator score >= 60
  - Supply razonable
  - Decimals válidos
- Elimina spam/scam
- **Eventos:** \TokenPassed\ / \TokenRejected\

### 4. SCORING (Puntuación)
- Calcula puntuación final (0-100):
  - 25% Authority score
  - 25% Creator score
  - 25% Supply analysis
  - 25% Metadata quality
- Mapea a riesgo: LOW_RISK / MEDIUM_POTENTIAL / HIGH_POTENTIAL
- **Evento:** \ScoreCalculated\

### 5. DECISION (Decisión)
- Score >= 70 ? SIGNAL_EARLY ?
- Score 50-70 ? MONITOR ??
- Score < 50 ? SKIP ?
- **Evento:** \DecisionMade\

### 6. SIGNALS (Generación)
- Genera signal: signal_id, confidence, reason
- Incluye metadata completa
- **Evento:** \SignalGenerated\

### 7. ALERTS (Alertas)
- Envía a Discord webhook
- Envía a Telegram bot
- Guarda en base de datos
- **Evento:** \AlertDispatched\

## Estado Actual (2026-03-18)

? **Completamente operacional**
- 127 eventos procesados
- 21 tokens analizados
- Pipeline completo funcionando
- Todos los 7 stages activos

## Próximos Pasos

1. [ ] Activar webhooks Discord/Telegram
2. [ ] Integrar análisis de money flows
3. [ ] Agregar análisis de calidad de buyers
4. [ ] Validar pools en Raydium
5. [ ] Implementar ML para predicciones
6. [ ] Crear dashboard en tiempo real

---

**Autor:** mamutrading520-coder
**Estado:** ? Operacional
**Última actualización:** 2026-03-18
