# Checklist de Puesta en Producción — OmniCore AI (SPEC-023)

> Verificaciones críticas antes de desplegar a infraestructura on-prem de producción.
> Clasificación: SENSIBLE (`.no-externo`). Todos los checkpoints corresponden a C2–C6.

**Responsable:** QUICKSILVER (DevOps) — con aprobación del Lead antes de pasar de DEV a PROD.

---

## Fase 1: Secretos y Seguridad (C3)

- [ ] **DB_PASSWORD**
  - [ ] Mínimo 32 caracteres
  - [ ] NO contiene palabras comunes ("postgres", "changeme", "demo")
  - [ ] Generado con `openssl rand -hex 32` o equivalente
  - [ ] Almacenado en secret manager (HashiCorp Vault, AWS Secrets Manager, etc.) **NO en .env**
  - [ ] `.env` del host de producción NO está en el repositorio ni en backups no cifrados

- [ ] **JWT_SECRET_KEY**
  - [ ] Mínimo 32 caracteres alfanuméricos
  - [ ] Generado con `openssl rand -hex 32`
  - [ ] Almacenado en secret manager (NO en .env ni en texto plano)
  - [ ] Diferente al secret de desarrollo

- [ ] **No hay secretos en código**
  - [ ] `git log --all -- "**/.env"` devuelve 0 resultados
  - [ ] `grep -r "changeme\|TODO.*secret\|password.*=" app/ src/` devuelve 0 resultados
  - [ ] `.env.example` contiene SOLO placeholders (NO valores reales)
  - [ ] Escaneo de secretos (`truffleHog`, `detect-secrets`) devuelve CLEAN

- [ ] **Acceso restringido**
  - [ ] Solo el equipo de DevOps tiene acceso al secret manager
  - [ ] Credenciales de BD no están en logs ni en salida de errores
  - [ ] Tokens JWT no están en logs (se truncan a primeros 8 caracteres si aparecen)

---

## Fase 2: Red y Firewall (C4, SENSIBLE)

- [ ] **Red `ia_internal` con egress bloqueado**
  - [ ] `docker compose config | grep -A2 "ia_internal:"` muestra `internal: true`
  - [ ] Contenedor Ollama SOLO en `ia_internal` (verificar `docker-compose.yml` línea 63)
  - [ ] Contenedor API está en AMBAS redes: `app` + `ia_internal` (líneas 131–133)
  - [ ] `docker exec crm_ia wget -T5 -qO- http://1.1.1.1` devuelve timeout/error (egress bloqueado)

- [ ] **Firewall del host**
  - [ ] Reglas `iptables`/`nftables` DROP de tráfico saliente desde Ollama a internet
  - [ ] Puertos expuestos restringidos:
    - [ ] `8000` (API): solo desde reverse proxy (127.0.0.1 o LB interno)
    - [ ] `5432` (PostgreSQL): SIN exposición a internet; solo red Docker
    - [ ] `6379` (Redis): SIN exposición a internet; solo red Docker
    - [ ] `11434` (Ollama): SIN exposición a internet; solo red `ia_internal`

- [ ] **Auditoría de egress: `check-externos-backend.sh`**
  - [ ] `bash backend/check-externos-backend.sh` devuelve "✓ APROBADO"
  - [ ] NO contiene URLs de OpenAI, Anthropic, Google, etc.
  - [ ] NO contiene imports de SDKs externos de IA
  - [ ] OLLAMA_BASE_URL apunta a `http://ia:11434` (interno)

---

## Fase 3: TLS/HTTPS (RNF-05, SPEC-021)

- [ ] **Reverse proxy (Nginx, Traefik, Caddy) configurado**
  - [ ] Termina TLS en puerto 443 (no 8000 expuesto)
  - [ ] Certificado válido (Let's Encrypt o CA corporativa)
  - [ ] Redirige HTTP plano → HTTPS
  - [ ] Reenvía a `api:8000` por red Docker interna

- [ ] **Headers de seguridad**
  - [ ] `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - [ ] `X-Content-Type-Options: nosniff`
  - [ ] `X-Frame-Options: DENY`
  - [ ] `Content-Security-Policy: default-src 'self'` (sin `unsafe-inline`)

- [ ] **Test de TLS**
  - [ ] `curl -v https://app.tudominio.com/healthz` devuelve 200 con certificado válido
  - [ ] `openssl s_client -connect app.tudominio.com:443` muestra certificado válido
  - [ ] Fecha de expiración del certificado ≥30 días en el futuro

---

## Fase 4: Base de datos (C2, SPEC-021)

- [ ] **Borrado lógico (C2)**
  - [ ] Todas las tablas transaccionales (`contacts`, `messages`, etc.) tienen flag `is_active` (o similar)
  - [ ] NON hay DELETE físicos en código de negocio; solo UPDATE `is_active = false`
  - [ ] Índices en `is_active` para filtrar activos por defecto

- [ ] **Migraciones versionadas (Alembic)**
  - [ ] `docker compose exec api alembic current` devuelve última versión sin error
  - [ ] `docker compose exec api alembic history` muestra todas las migraciones (sin downgrade pendiente)
  - [ ] Cada migración tiene `up()` y `down()` reversibles (si aplicable)

- [ ] **Datos de prueba/demo REMOVIDOS**
  - [ ] NO hay datos ficticios de SPEC-001 en la BD de PROD
  - [ ] Seed es limpio: solo un tenant/usuario admin de operación
  - [ ] Credenciales del seed admin FUERTES y almacenadas en secret manager

- [ ] **Backups configurados**
  - [ ] Script `backup-crm.sh` está en cron del host (ejecuta diariamente)
  - [ ] Últimas 7 backups están disponibles en `/backups/crm/`
  - [ ] Backups se comprimen y se replican a servidor remoto seguro (rsync, S3 cifrado)
  - [ ] Test de restauración desde backup completado exitosamente (últimas 30 días)

- [ ] **Retención de datos (HABEAS DATA)**
  - [ ] `DATA_RETENTION_DAYS` se configura según política corporativa (p. ej. 90 días)
  - [ ] Job `retention_job` está configurado para ejecutarse (p. ej. diariamente a las 3 AM)
  - [ ] Anonimización solo toca contactos `is_active = false` (borrado lógico, no DELETE físico)

- [ ] **Auditoría de acceso**
  - [ ] Logs de auditoría de acceso a datos personales están habilitados
  - [ ] Endpoint `GET /api/v1/contacts/{id}/personal-data/export` funciona
  - [ ] Endpoint `POST /api/v1/contacts/{id}/personal-data/erase` funciona (anonimiza, no borra)

---

## Fase 5: Modelos Locales (SPEC-016)

- [ ] **Modelos descargados y verificados**
  - [ ] `docker compose exec ia ollama pull qwen2.5:7b-instruct` completó exitosamente
  - [ ] `docker compose exec ia ollama pull nomic-embed-text` completó exitosamente
  - [ ] `docker compose exec ia curl http://localhost:11434/api/tags | jq '.models | length'` devuelve 2

- [ ] **Configuración de modelo**
  - [ ] `.env` especifica `OLLAMA_MODEL=qwen2.5:7b-instruct` (o versión Q4 si CPU)
  - [ ] `.env` especifica `OLLAMA_EMBED_MODEL=nomic-embed-text`
  - [ ] Timeouts configurados: `AI_CONNECT_TIMEOUT_SECONDS=5`, `AI_REQUEST_TIMEOUT_SECONDS=30`

- [ ] **Hardware verificado**
  - [ ] [ ] GPU disponible: ver `docker compose stats | grep crm_ia`
    - CPU con GPU: Ollama muestra "CUDA: yes" o "ROCm: yes" en logs
    - CPU sin GPU: Usar modelo Q4 (`qwen2.5:7b-instruct-q4_1`); p95 RAG ~15–30 s
  - [ ] RAM mínima: ≥16 GB (≥32 GB recomendado)
  - [ ] Espacio disco: ≥100 GB disponibles para BD + modelos + cache

- [ ] **Test de inferencia e2e**
  - [ ] `curl -X POST http://localhost:8000/api/v1/rag/draft -H "..." -d '...'` devuelve respuesta en < 10 s (GPU) o < 30 s (CPU Q4)
  - [ ] Respuesta incluye ≥1 cita (source + excerpt + similarityScore)
  - [ ] No hay llamadas a APIs externas en logs de Ollama

---

## Fase 6: Observabilidad (RNF-06, SPEC-022)

- [ ] **Health checks**
  - [ ] `GET /healthz` responde 200 sin latencia aparente
  - [ ] `GET /readyz` responde 200 con todos los checks OK
  - [ ] Healthchecks en `docker-compose.yml` configurados con `interval: 10s`, `timeout: 5s`, `retries: 5`

- [ ] **Logs estructurados (JSON)**
  - [ ] `docker compose logs api --tail=10 | jq . | head -5` parsea sin error
  - [ ] Logs incluyen `tenant_id`, `request_id`, `user_id`, `latency_ms`
  - [ ] Nivel de log en PROD: `INFO` (no `DEBUG`)
  - [ ] NO hay secretos en logs (DB_PASSWORD, JWT, tokens truncados)

- [ ] **Métricas (Prometheus)**
  - [ ] `curl http://localhost:8000/metrics | head -20` devuelve formato OpenMetrics válido
  - [ ] Métricas incluyen:
    - [ ] `http_request_duration_seconds_bucket` (latencia de endpoints REST)
    - [ ] `ai_request_duration_seconds_bucket` (latencia de llamadas a Ollama)
    - [ ] `websocket_connections` (número de clientes WebChat activos)

- [ ] **Alertas configuradas** (si Prometheus/Grafana está disponible)
  - [ ] Alerta si `/healthz` devuelve != 200
  - [ ] Alerta si p95 latencia RAG > 10 s (GPU) o > 35 s (CPU Q4)
  - [ ] Alerta si PostgreSQL pool está agotado (todas las conexiones en uso)
  - [ ] Alerta si Redis está caído o lento

---

## Fase 7: Multi-tenant y RLS (SPEC-012, SPEC-013)

- [ ] **RLS (Row-Level Security) activo**
  - [ ] Tabla `contacts` tiene política RLS: `tenant_id = current_setting('app.tenant_id')`
  - [ ] Tabla `messages` tiene política RLS: `tenant_id = current_setting('app.tenant_id')`
  - [ ] Tabla `documents` tiene política RLS por tenant (no cross-tenant reads)
  - [ ] Test cross-tenant falla con "policy violation" (HAWKEYE CE-22)

- [ ] **Inyección de tenant_id**
  - [ ] Middleware en API establece `set_config('app.tenant_id', tenant_id)` en cada request
  - [ ] Token JWT contiene `tenant_id` y se valida con el request
  - [ ] NO hay hardcoding de `WHERE tenant_id = ...` en queries (Django ORM / SQLAlchemy filtra por RLS)

- [ ] **Test de aislamiento**
  - [ ] `pytest tests/test_rls_isolation.py::test_cross_tenant_contact_access` **FALLA** (esperado)
  - [ ] `pytest tests/test_rls_isolation.py::test_same_tenant_access` **PASA**

---

## Fase 8: Integración SPA (SPEC-020)

- [ ] **Feature flag `VITE_USE_REAL_API`**
  - [ ] En PROD: `VITE_USE_REAL_API=true` (consumir APIs reales, no mocks)
  - [ ] En DEV: `VITE_USE_REAL_API=false` (permitir desarrollo offline con mocks)

- [ ] **URLs de API**
  - [ ] `VITE_API_BASE_URL=https://app.tudominio.com/api/v1` (HTTPS, no HTTP)
  - [ ] `VITE_WS_BASE_URL=wss://app.tudominio.com/api/v1` (WSS, no WS)
  - [ ] NO contienen IPs públicas ni dominios temporales (p. ej. ngrok)

- [ ] **CORS configurado**
  - [ ] `CORS_ORIGINS` contiene SOLO dominios permitidos (ej. `https://app.tudominio.com`)
  - [ ] NO contiene `*` (comodín)
  - [ ] NO tiene `localhost:3000` ni `localhost:5173` (dev-only)

- [ ] **Build de SPA optimizado**
  - [ ] `npm run build` completa sin error y sin warnings críticos
  - [ ] `npm run lint` devuelve 0 errores
  - [ ] `npm run test` devuelve todos los tests pasando (32/32 contraste + smoke)
  - [ ] `npm run check:externos` devuelve "✓ APROBADO"

---

## Fase 9: Pruebas de Carga (SPEC-022, THOR)

- [ ] **Latencia p95 dentro de SLA**
  - [ ] `GET /api/v1/contacts`: p95 ≤ 200 ms ✓
  - [ ] `POST /api/v1/rag/draft` (GPU): p95 ≤ 6 s ✓
  - [ ] `POST /api/v1/rag/draft` (CPU Q4): p95 ≤ 30 s (documentado) ✓

- [ ] **Carga de concurrencia**
  - [ ] 20 usuarios concurrentes por 2 minutos sin errores 5xx
  - [ ] Tasa de error < 1%
  - [ ] DB pool y Redis no agotados (ver `docker compose stats`)

- [ ] **Prueba de egress vacío (HAWKEYE CE-21)**
  - [ ] Captura de red durante prueba de carga: sin salida del contenedor `ia` a IPs públicas
  - [ ] Netstat inside `crm_ia`: solo conexiones a redes internas (172.20.x.x, 172.21.x.x)

---

## Fase 10: Documentación (SPEC-023)

- [ ] **OPERACION.md completado**
  - [ ] Sección "Requisitos previos" incluye hardware GPU/CPU recomendado
  - [ ] Sección "Descarga de modelos locales" documenta comandos `ollama pull` dentro del contenedor
  - [ ] Sección "Verificación de salud" incluye todos los healthchecks
  - [ ] Sección "Descarga de modelos" documenta fallback CPU Q4

- [ ] **RUNBOOK.md completado**
  - [ ] Sección "Arranque y parada" incluye procedimiento ordenado
  - [ ] Sección "Backups de PostgreSQL" incluye comando `pg_dump` y restore
  - [ ] Sección "Respuesta a incidentes" cubre los 5+ incidentes más comunes
  - [ ] Sección "Rollback" documenta downgrade de migraciones y cambio de imagen Docker
  - [ ] Sección "Verificación de egress bloqueado" incluye pruebas manuales

- [ ] **DEPLOYMENT_CHECKLIST.md (este archivo) completado**
  - [ ] Todos los items de Fase 1–10 marcados como [ ]
  - [ ] Este checklist está en el repositorio (accesible antes del deploy)

- [ ] **EXAMPLES_OPENAPI.json completado**
  - [ ] Incluye ejemplos de login, crear conversación, enviar mensaje, RAG draft
  - [ ] Cada ejemplo muestra request/response reales (no genéricos)
  - [ ] URLs apuntan a `http://localhost:8000` (compatible con desarrollo) o `https://app.tudominio.com` (PROD)

- [ ] **README.md actualizado**
  - [ ] Referencia a OPERACION.md para deploy on-prem
  - [ ] Referencia a RUNBOOK.md para operación y troubleshooting
  - [ ] Menciona que es proyecto SENSIBLE (`.no-externo`)
  - [ ] Enlace a ADRs (ADR-003, ADR-004, ADR-005) para decisiones técnicas

---

## Fase 11: Aprobación del Lead (C6)

- [ ] **Lead ha revisado y aprobado el deploy**
  - [ ] Email/Slack: "APROBADO SPEC-023 para despliegue a PROD"
  - [ ] Lead confirma que entiende degradación CPU (p95 ~15–30 s) si no hay GPU
  - [ ] Lead confirma que se han completado TODAS las fases 1–10

- [ ] **Plan de rollback comunicado al Lead**
  - [ ] Lead entiende cómo se puede revertir rápidamente (< 5 minutos)
  - [ ] Lead tiene acceso a secret manager para emergencias
  - [ ] Teléfono de escalada / contacto 24x7 documentado

- [ ] **Ventana de mantenimiento comunicada**
  - [ ] Tiempo estimado de deploy: 30–60 minutos (dependiendo de descarga de modelos)
  - [ ] Mensajería a usuarios: "Sistema en mantenimiento..."
  - [ ] DNS/LB: cambio de apuntador a nuevo host planificado

---

## Fase 12: Despliegue Ejecutado (QUICKSILVER)

- [ ] **Notificación a Telegram ANTES de iniciar**
  - [ ] Canal `#deployments`: "Iniciando despliegue SPEC-023 a PROD — ventana 20:00–21:00 UTC"
  - [ ] Incluye plan de rollback y contacto de escalada

- [ ] **Pasos del deploy ejecutados en orden**
  1. [ ] Reservar DNS/LB (apuntador temporal a staging)
  2. [ ] Pausa de tráfico en LB (si lo hay) o notificación de downtime
  3. [ ] `docker compose up -d` en host de PROD
  4. [ ] Esperar healthchecks (máximo 60 s)
  5. [ ] Descargar modelos Ollama (máximo 45 min)
  6. [ ] `alembic upgrade head` (migraciones)
  7. [ ] Seed de datos (tenant admin)
  8. [ ] `check-externos-backend.sh` (verificación SENSIBLE)
  9. [ ] Prueba manual de endpoints clave (login, RAG, WebChat)
  10. [ ] Cambiar apuntador DNS/LB a PROD
  11. [ ] Monitoreo 24 horas: logs, métricas, alertas

- [ ] **Notificación a Telegram TRAS completar**
  - [ ] Canal `#deployments`: "SPEC-023 desplegada a PROD — todos los healthchecks OK"
  - [ ] Incluye resumen de cambios (fecha, versión, duración del deploy)
  - [ ] Confirmación de "cero salida externa" (CE-21 ✓)

- [ ] **Monitoreo post-deploy (primeras 24 horas)**
  - [ ] Tasa de error < 0.5%
  - [ ] Latencia p95 dentro de SLA
  - [ ] No hay alertas de seguridad/egress
  - [ ] RLS está activo (prueba cross-tenant falla como se espera)

---

## Fase 13: Cierre de SPEC-023

- [ ] **Documentación final**
  - [ ] Fecha/hora del deploy registrada
  - [ ] Versión de código desplegada (ej. commit SHA)
  - [ ] Hardware final confirmado (GPU? VRAM? CPU cores?)
  - [ ] Incidentes durante deploy documentados (si los hubo)

- [ ] **Estado en `.swarm/specs.json`**
  - [ ] SPEC-023 marcada como `CERRADA`
  - [ ] Fecha de cierre: hoy
  - [ ] Criterios de aceptación: todos cumplidos (CE-28, CE-29)

- [ ] **Entregables finales entregados**
  - [ ] OPERACION.md
  - [ ] RUNBOOK.md
  - [ ] DEPLOYMENT_CHECKLIST.md (este archivo, marcado como completado)
  - [ ] EXAMPLES_OPENAPI.json
  - [ ] README.md actualizado con referencias
  - [ ] Todos en repositorio y versionados

---

## Resumen: Estado de Deploy

| Componente | Estado | Responsable |
|---|---|---|
| Secretos fuertes (C3) | ✓ | DevOps |
| Red `ia_internal` egress bloqueado | ✓ | DevOps |
| TLS/HTTPS con certificado válido | ✓ | DevOps + Infra |
| BD con borrado lógico (C2) | ✓ | Backend |
| Modelos locales descargados | ✓ | DevOps |
| Observabilidad (healthz, logs, métricas) | ✓ | Backend + DevOps |
| RLS multi-tenant funcional | ✓ | Backend |
| SPA conectada a APIs reales | ✓ | Frontend |
| Pruebas de carga cumplidas (THOR) | ✓ | QA |
| Documentación completa | ✓ | DevOps (QUICKSILVER) |
| Aprobación del Lead | ⏳ | Lead |
| Deploy ejecutado | ⏳ | QUICKSILVER |

---

**Última actualización:** 2026-09-18 · **Responsable:** QUICKSILVER
**Siguiente paso:** Presentar checklist al Lead para aprobación final antes de Phase 12.
