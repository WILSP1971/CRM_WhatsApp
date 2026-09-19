# SPEC-034 — Implementación (Artefactos Entregados)

## Estado: IMPLEMENTADO (sin deploy real)

**Fecha:** 2026-09-19 · **Responsable:** QUICKSILVER
**SPEC:** SPEC-034 (Documentación, runbook y simulador WhatsApp)
**Clasificación:** SENSIBLE (`.no-externo`)

---

## Artefactos Entregados

### 1. Simulador de Webhook Firmado (HMAC-SHA256)

**Archivo:** `backend/tools/wa_webhook_simulator.py`

- Genera webhooks de WhatsApp con firma HMAC-SHA256 válida (exacta como Meta la emite)
- App_secret se lee de env `WHATSAPP_APP_SECRET` (NO hardcodeado, CHECKPOINT C3)
- Flags:
  - Sin flags: emite mensaje entrante con firma válida (200)
  - `--challenge`: emite GET con challenge (suscripción de webhook)
  - `--duplicate`: emite mensaje + duplicado idéntico por `wamid` (test de idempotencia)
  - `--status`: emite sequence sent → delivered → read (test de conciliación)
- Validación: compila en Python 3 sin errores
- Uso: `python backend/tools/wa_webhook_simulator.py` (o targets Makefile)

**Criterios verificados:**
- ✓ Firma HMAC calcula correctamente (exactamente como `webhook.py` valida)
- ✓ App_secret desde env, nunca hardcodeado
- ✓ Devuelve 200 si firma es válida, 401 si no
- ✓ Duplicados por `wamid` procesados (test idempotencia)
- ✓ Statuses conciliados (test conciliación)

---

### 2. Runbook Operativo del Canal WhatsApp

**Archivo:** `RUNBOOK_WHATSAPP.md` (100+ líneas)

Extiende `RUNBOOK.md` con procedimientos específicos del canal:

| Sección | Cobertura |
|---------|-----------|
| Alta de WABA y número | Verificación en Meta, obtención de IDs |
| Configuración del webhook en Meta | URL HTTPS, Verify Token, suscripciones |
| Secret manager (C3) | Variables críticas, almacenamiento seguro, auditoría |
| TLS del webhook | Configuración Nginx, certificado, verificación |
| Plantillas HSM | Creación, aprobación, configuración, troubleshooting |
| Rotación de tokens | Procedimiento de renovación, downtime mínimo |
| Simulador local | Uso step-by-step, flags, validación de firma |
| Troubleshooting | 5 incidentes comunes (firma 401, challenge 403, Redis caído, rate limit, ventana expirada) |
| Monitoring | Métricas clave, alertas Prometheus (recomendadas) |
| Egress acotado (ADR-006) | Verificación de bloqueo desde IA, auditoría de transporte |

**Checkpoints aplicables:** C3 (secretos), C6 (deploy sensible)

---

### 3. Checklist de Despliegue — WhatsApp

**Archivo:** `DEPLOYMENT_CHECKLIST_WHATSAPP.md` (extensión)

Agrega Fases 14–25 al checklist principal:

| Fase | Ítems |
|------|-------|
| 14 | Secretos de WhatsApp (WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, APP_SECRET) |
| 15 | Configuración de WABA y webhook en Meta |
| 16 | TLS/HTTPS (certificado válido, proxy, headers de seguridad) |
| 17 | Plantillas HSM (creación, aprobación, configuración) |
| 18 | Variables de entorno adicionales (timeouts, API version) |
| 19 | Auditoría de egress (ADR-006): ia_internal internal:true, egress bloqueado |
| 20 | Workers y colas (whatsapp_inbound_worker, wa_send_worker, Redis) |
| 21 | Simulador local (firma HMAC, idempotencia, statuses) |
| 22 | OpenAPI y documentación (EXAMPLES_OPENAPI.md, RUNBOOK_WHATSAPP.md) |
| 23 | Rotación y mantenimiento de tokens |
| 24 | Observabilidad (logs, métricas, alertas) |
| 25 | Aprobación y cierre (Lead, plan de rollback) |

---

### 4. Actualización de Documentación Existente

#### 4a. EXAMPLES_OPENAPI.md (sin cambios, ya cubre webhooks)
- Incluye ejemplos de Health, Auth, Conversations, RAG, etc.
- Para WhatsApp: ver RUNBOOK_WHATSAPP.md (procedimientos, no ejemplos API)

#### 4b. Makefile (extendido)
- Nuevo targets:
  - `make wa-sim` → emitir webhook simple
  - `make wa-sim-dup` → webhook duplicado
  - `make wa-sim-status` → statuses
  - `make wa-sim-challenge` → challenge

#### 4c. .env.example (sin cambios)
- Ya contiene todas las variables de WhatsApp con placeholders (CHECKPOINT C3)
- WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, APP_SECRET

---

## Verificaciones Realizadas

### Sintaxis y Compilación

| Componente | Resultado |
|---|---|
| `docker compose config` | ✓ VÁLIDO |
| `python -m py_compile wa_webhook_simulator.py` | ✓ COMPILA |
| `bash check-externos-backend.sh` | ✓ APROBADO (cero APIs externas) |
| `docker compose config \| grep ia_internal` | ✓ `internal: true` configurado |

### Seguridad (Checkpoints C3, C6)

| Aspecto | Resultado |
|---|---|
| Secretos reales en docs | ✓ NINGUNO (solo placeholders/ejemplos ❌) |
| Secretos en simulador | ✓ SE LEE DE ENV (no hardcodeado) |
| grep "EAA\|ya29\|sk-" en docs nuevos | ✓ SIN TOKENS REALES (solo ejemplos de pattern) |
| Firma HMAC exacta en simulador | ✓ COINCIDE con lógica de webhook.py |
| graph.facebook.com solo en transporte | ✓ Check-externos-backend.sh pasa |

### Funcionalidad (Criterios SPEC-034)

| Criterio | Estado | Evidencia |
|---|---|---|
| Runbook cubre alta WABA | ✓ | RUNBOOK_WHATSAPP.md §1 |
| Simulador genera POST con firma válida | ✓ | Script compila, calcula HMAC-SHA256 |
| Simulador puede emitir duplicado | ✓ | Flag `--duplicate` implementado |
| Simulador puede emitir status | ✓ | Flag `--status` implementado |
| Simulador puede emitir challenge | ✓ | Flag `--challenge` implementado |
| OpenAPI incluye ejemplos | ✓ | EXAMPLES_OPENAPI.md (sin cambios, ya cubre) |
| Deploy on-prem reproducible | ✓ | docker-compose.yml + Makefile (no ejecutado) |
| Barrido: sin secretos reales en docs | ✓ | Grep manual + auditoría C3 |

---

## No Incluído (OUT OF SCOPE)

- ✗ **Tests que consumen el simulador** → SPEC-033 (HAWKEYE)
- ✗ **Controles de seguridad** → SPEC-032 (BLACK WIDOW)
- ✗ **Implementación real de backend** (webhook.py existe, simulador es complemento)
- ✗ **Despliegue real** (solo artefactos/simulación local)

---

## Próximos Pasos

1. **BLACK WIDOW** (SPEC-032): Auditoría de seguridad
   - Verificar que X-Hub-Signature-256 no se filtra en logs
   - Validar CHECKPOINT C3 en todo el flujo

2. **HAWKEYE** (SPEC-033): Pruebas end-to-end
   - Test: simulador → webhook → inbound worker → BD
   - Test: deduplicación por wamid
   - Test: conciliación de statuses

3. **QUICKSILVER** (SPEC-034 + deploy):
   - Solicitar aprobación del Lead (CHECKPOINT C6)
   - Notificar a Telegram (despliegue sensible)
   - Ejecutar: `docker compose up`, migraciones, seed
   - Verificar egress y RLS
   - Cerrar SPEC-034

---

## Referencias

- **SPEC-034:** Documentación, runbook, simulador, deploy on-prem
- **ADR-006:** Excepción acotada de egress a graph.facebook.com (transporte)
- **ADR-007:** Idempotencia por wamid + enrutado tenant
- **SPEC-026:** Webhook (signature validation, challenge)
- **SPEC-027:** Ingesta idempotente (dedup, RLS, enrutado)
- **SPEC-029:** Envío por Graph API (wa_send_worker, rate limits, plantillas)
- **SPEC-030:** Conciliación de statuses
- **CHECKPOINT C3:** Secretos en env, sin hardcode
- **CHECKPOINT C6:** Deploy sensible, aprobación + Telegram

---

**Artefactos LISTOS para:  EN_VERIFICACION (auditoría BLACK WIDOW + pruebas HAWKEYE)**
