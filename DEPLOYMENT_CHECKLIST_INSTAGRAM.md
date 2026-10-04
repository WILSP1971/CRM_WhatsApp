# Checklist de Despliegue — Canal Instagram Direct Message (SPEC-085..091, cierra PLAN-012)

> Verificaciones adicionales para despliegue on-prem cuando se integra el canal Instagram DM.
> Extiende `DEPLOYMENT_CHECKLIST.md` con ítems específicos de Instagram, espejo de `DEPLOYMENT_CHECKLIST_WHATSAPP.md`.
> 🔴 **El deploy a producción de este canal requiere aprobación explícita del Lead (C6) — ver Fase 7.** NO ejecutado como parte de SPEC-091 (solo preparado/documentado).

## Fase 1: Instagram — Secretos y Configuración (C3)

- [ ] **INSTAGRAM_APP_SECRET**
  - [ ] Obtenido de Meta App Settings → Basic (misma app que WhatsApp, si se comparte, o app dedicada)
  - [ ] Almacenado en secret manager (HashiCorp Vault, AWS Secrets Manager)
  - [ ] NO en `.env` del repo
  - [ ] Usado para calcular firma HMAC-SHA256 (`X-Hub-Signature-256`)
  - [ ] Nunca en logs

- [ ] **INSTAGRAM_VERIFY_TOKEN**
  - [ ] Generado: `openssl rand -hex 16`
  - [ ] DISTINTO de `WHATSAPP_VERIFY_TOKEN`
  - [ ] Almacenado en secret manager
  - [ ] Configurado en Meta Dashboard → Instagram → Webhooks (exactamente igual)

- [ ] **INSTAGRAM_PAGE_ACCESS_TOKEN**
  - [ ] Obtenido tras vincular Página de Facebook + cuenta IG Business
  - [ ] Permisos `instagram_manage_messages` concedidos (requiere App Review para usuarios reales — ver runbook)
  - [ ] Almacenado en secret manager
  - [ ] Usado SOLO en header `Authorization: Bearer` por `instagram_send_worker`

- [ ] **INSTAGRAM_BUSINESS_ACCOUNT_ID**
  - [ ] Obtenido de Graph API Explorer (`GET /me/accounts`)
  - [ ] En multi-tenant: registrado en la tabla `instagram_accounts` (SPEC-085), no solo en env
  - [ ] Id público (NO es secreto fuerte), pero SÍ debe coincidir con la cuenta real vinculada

- [ ] **Auditoría de exposición (C3)**
  - [ ] `git log --all -p -- ".env"` NO contiene tokens/secretos reales
  - [ ] `.env.example` contiene SOLO placeholders de Instagram
  - [ ] `grep -r "EAA\|ya29\|sk-\|akey" backend/app/` devuelve 0 resultados
  - [ ] Barrido con `truffleHog`/`detect-secrets`: CLEAN

---

## Fase 2: Instagram — Alta de app de Meta y cuenta IG Business

- [ ] **App de Meta for Developers**
  - [ ] Producto "Instagram"/Messenger añadido
  - [ ] Página de Facebook vinculada
  - [ ] Cuenta de Instagram Business (o Creator) vinculada a esa Página

- [ ] **🔴 Meta App Review (BLOQUEANTE para usuarios reales, R-110)**
  - [ ] Permiso `instagram_manage_messages` solicitado
  - [ ] Permiso `instagram_basic` solicitado
  - [ ] Permiso `pages_messaging` solicitado
  - [ ] Estado: `PENDIENTE` / `EN REVISIÓN` / `APROBADO` (documentar cuál)
  - [ ] **Responsabilidad: Lead/negocio** (trámite externo con Meta, fuera del alcance de desarrollo — PLAN-012 §OUT)

- [ ] **Webhook en Meta Dashboard**
  - [ ] URL: `https://api.tudominio.com/api/v1/instagram/webhook` (HTTPS obligatorio, path DISTINTO de WhatsApp)
  - [ ] Verify Token: coincide exactamente con `INSTAGRAM_VERIFY_TOKEN`
  - [ ] Suscripciones: `messages`, `message_deliveries` (NO `messaging_postbacks`/`messaging_referrals`)
  - [ ] Challenge respondido correctamente

- [ ] **Cuentas de rol de prueba** (para verificación SIN esperar App Review)
  - [ ] Al menos 1 cuenta admin/tester/developer añadida en Meta Dashboard → Roles
  - [ ] Documentado qué se pudo verificar con esas cuentas vs qué queda diferido (ver RUNBOOK_INSTAGRAM.md §"Informe de alcance E2E")

---

## Fase 3: Instagram — Workers y Colas

- [ ] **Workers de Instagram están en docker-compose.yml** (YA DEFINIDOS, verificar al desplegar)
  - [ ] `instagram_inbound_worker`: consumidor de `ig:inbound` (SPEC-087), SIN egress
  - [ ] `instagram_send_worker`: consumidor de `ig:outbound` (SPEC-089), CON egress acotado a `graph.facebook.com`
  - [ ] Ambos con `depends_on: [db, redis]`
  - [ ] Variables de entorno correctas (ver Fase 1)

- [ ] **Colas Redis persistentes**
  - [ ] `ig:inbound` (webhooks entrantes) — DISTINTA de `wa:inbound` (verificado por test `test_instagram_queue_is_distinct_from_whatsapp_queue`)
  - [ ] `ig:outbound` (mensajes a enviar tras aprobación humana)
  - [ ] No hay jobs atascados: `docker compose exec redis redis-cli KEYS "ig:*" | wc -l`

- [ ] **Test de workers (sin deploy real)**
  - [ ] Simulador genera webhook: `python backend/tools/ig_webhook_simulator.py`
  - [ ] Webhook encolado en `ig:inbound`
  - [ ] Worker procesa: logs muestran persistencia del `Message`

---

## Fase 4: Instagram — Simulador de Webhook Firmado (SPEC-091)

- [ ] **Simulador existe y funcional**
  - [ ] Archivo: `backend/tools/ig_webhook_simulator.py`
  - [ ] Compila: `python -m py_compile backend/tools/ig_webhook_simulator.py`

- [ ] **Test de firma HMAC** — verificado (SPEC-091, 2026-10-04)
  - [ ] `python backend/tools/ig_webhook_simulator.py` → 200, encolado en `ig:inbound`

- [ ] **Test de rechazo (firma inválida/ausente)** — verificado
  - [ ] `python backend/tools/ig_webhook_simulator.py --bad-signature` → 401
  - [ ] `python backend/tools/ig_webhook_simulator.py --no-signature` → 401

- [ ] **Test de idempotencia (`--duplicate`)** — verificado
  - [ ] Ambos webhooks 200; 1 solo `Message` en BD (SPEC-087/091)

- [ ] **Test de attachments (`--attachment`)** — verificado
  - [ ] `media_url`/`media_type` persistidos tal cual (SPEC-088)

- [ ] **Test de challenge (`--challenge` / `--challenge --bad-token`)** — verificado
  - [ ] Token correcto → 200 + `hub.challenge` exacto; token incorrecto → 403

---

## Fase 5: Instagram — Auditoría de Egress (ADR-006 ampliada)

- [ ] **Egress acotado verificado**
  - [ ] `bash backend/check-externos-backend.sh .` → "APROBADO"
  - [ ] `instagram_inbound_worker` SIN egress real (solo persiste URLs, nunca descarga)
  - [ ] `instagram_send_worker` CON egress acotado a `graph.facebook.com` (mismo host ya autorizado para WhatsApp, ADR-006 ampliada — NO es egress nuevo)
  - [ ] `api` (webhook) solo RECIBE, nunca egresa hacia Meta en esta ruta

---

## Fase 6: Instagram — Documentación

- [ ] **RUNBOOK_INSTAGRAM.md completado**
  - [ ] Alta de app de Meta / cuenta IG Business
  - [ ] Webhook + verify-token
  - [ ] Secret manager de `INSTAGRAM_*`
  - [ ] Ventana de mensajería (message tags, NO HSM)
  - [ ] Rotación de tokens
  - [ ] Simulador local
  - [ ] Limitación de `estado_entrega` (no progresa a entregado/leído)
  - [ ] 🔴 Bloqueo de Meta App Review EXPLÍCITO
  - [ ] Informe de alcance E2E (verificado vs diferido)

- [ ] **DEPLOYMENT_CHECKLIST.md (principal) referencia este archivo**

---

## Fase 7: Instagram — Aprobación y Cierre (🔴 C6, SENSIBLE)

- [ ] **Lead ha revisado SPEC-091**
  - [ ] Todos los criterios de aceptación entendidos, incluida la salvedad E2E de R-110
  - [ ] Aprobación explícita: "APROBADO SPEC-091" + aprobación de DEPLOY (son dos aprobaciones distintas — SPEC-091 cubre pruebas/runbook; el deploy real es un checkpoint C6 adicional)
  - [ ] Fecha de aprobación registrada

- [ ] **Notificación antes de desplegar** (mismo patrón que deploys anteriores con secretos reales diferidos)

- [ ] **Plan de rollback comunicado**
  - [ ] Desactivar webhook de Instagram en Meta (quitar suscripción) sin afectar WhatsApp
  - [ ] Detener `instagram_inbound_worker`/`instagram_send_worker` sin afectar sus pares de WhatsApp
  - [ ] Tiempo de rollback estimado: ~5 minutos

- [ ] **Estado de este deploy en esta SPEC (SPEC-091): NO EJECUTADO**
  - [ ] Simulador y suite de tests: verificados en local (ver RUNBOOK_INSTAGRAM.md)
  - [ ] `docker compose up` de los servicios de Instagram: NO ejecutado contra ningún entorno real (fuera de alcance de HAWKEYE en esta tarea — requiere aprobación explícita C6 del Lead, solicitada por separado)
  - [ ] Secretos reales: DIFERIDOS (ninguno generado/usado en esta SPEC)

---

## Resumen: Estado de Instagram

| Componente | Estado | Responsable |
|---|---|---|
| Secretos `INSTAGRAM_*` (C3, placeholders) | ✓ | Backend (`config.py`, `.env.example`) |
| Simulador de webhook firmado | ✓ | HAWKEYE (SPEC-091) |
| Suite de tests (idempotencia, cross-tenant, parser, media, firma) | ✓ | HAWKEYE/Backend (SPEC-086..091) |
| Egress acotado a Meta (ADR-006 ampliada) | ✓ | ADR-006 + `check-externos-backend.sh` |
| Documentación (runbook, checklist) | ✓ | HAWKEYE (SPEC-091) |
| Meta App Review aprobado | ⏳ BLOQUEADO (externo) | Lead/negocio |
| Webhook configurado en Meta con credenciales reales | ⏳ DIFERIDO | Lead/negocio + QUICKSILVER |
| `docker compose up` de servicios IG en producción | ⏳ NO EJECUTADO | QUICKSILVER (requiere aprobación C6) |
| Lead aprobación de deploy (C6) | ⏳ PENDIENTE | Lead humano |

---

**Última actualización:** 2026-10-04 · **SPEC:** SPEC-091 (cierra PLAN-012)
**Referencias:** DEPLOYMENT_CHECKLIST.md, DEPLOYMENT_CHECKLIST_WHATSAPP.md, RUNBOOK_INSTAGRAM.md, ADR-006 (ampliada)
