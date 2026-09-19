# Checklist de Despliegue — Canal WhatsApp (SPEC-034)

> Verificaciones adicionales para despliegue on-prem cuando se integra el canal WhatsApp.
> Extiende `DEPLOYMENT_CHECKLIST.md` con ítems específicos de WhatsApp.

## Fase 14: WhatsApp — Secretos y Configuración (C3)

- [ ] **WHATSAPP_TOKEN (access token)**
  - [ ] Generado en Meta API Dashboard → Settings → User Token Manager
  - [ ] Long-lived (validez ~60 días)
  - [ ] Almacenado en secret manager (HashiCorp Vault, AWS Secrets Manager)
  - [ ] NO en `.env`, NO en .gitignore track
  - [ ] Contraseña fuerte: caracteres aleatorios, sin palabras conocidas

- [ ] **WHATSAPP_PHONE_NUMBER_ID**
  - [ ] Obtenido de Meta → Phone Numbers (debe estar verificado/activo)
  - [ ] Almacenado en secret manager
  - [ ] Coincide con el número dado de alta en Meta

- [ ] **WHATSAPP_VERIFY_TOKEN**
  - [ ] Generado: `openssl rand -hex 16`
  - [ ] Mínimo 32 caracteres
  - [ ] Almacenado en secret manager
  - [ ] Configurado en Meta Dashboard → Webhook Settings → Verify Token (exactamente igual)

- [ ] **WHATSAPP_APP_SECRET**
  - [ ] Obtenido de Meta App Settings → Basic
  - [ ] Almacenado en secret manager
  - [ ] Usado para calcular firma HMAC-SHA256 (X-Hub-Signature-256)
  - [ ] Nunca en logs

- [ ] **Auditoría de exposición (C3)**
  - [ ] `git log --all -p -- ".env"` NO contiene tokens/secretos reales
  - [ ] `.env.example` contiene SOLO placeholders
  - [ ] `grep -r "EAA\|ya29\|sk-\|akey" app/` devuelve 0 resultados (no tokens hardcodeados)
  - [ ] Barrido con `truffleHog` o `detect-secrets`: CLEAN

---

## Fase 15: WhatsApp — Configuración de WABA y Webhook

- [ ] **WABA (WhatsApp Business Account)**
  - [ ] Creado o vinculado en Meta for Developers
  - [ ] Empresa verificada (paso de verificación completado)
  - [ ] Acceso confirmado en Meta Dashboard

- [ ] **Número de WhatsApp**
  - [ ] Dado de alta en Meta → Phone Numbers
  - [ ] Verificación completada (código SMS recibido y confirmado)
  - [ ] Estado: "Active" en Meta Dashboard
  - [ ] PHONE_NUMBER_ID documentado (guardado en secret manager)

- [ ] **Webhook en Meta Dashboard**
  - [ ] URL: `https://api.tudominio.com/api/v1/whatsapp/webhook` (HTTPS obligatorio)
  - [ ] Verify Token: coincide exactamente con WHATSAPP_VERIFY_TOKEN
  - [ ] Suscripciones: ✓ Messages, ✓ Message Status (otros sin marcar)
  - [ ] Challenge respondido correctamente (Meta valida automáticamente)

- [ ] **Desuscripción automática (rollback)**
  - [ ] Si hace falta desplegar sin WhatsApp, remover webhook de Meta
  - [ ] Comando `DELETE` a Meta Graph API (si aplicable)

---

## Fase 16: WhatsApp — Configuración de TLS/HTTPS

- [ ] **Certificado TLS válido**
  - [ ] No autofirmado (Let's Encrypt o CA corporativa)
  - [ ] Cadena completa: certificado + intermediarios + root
  - [ ] Válido para el dominio de webhook (ej. `api.tudominio.com`)
  - [ ] Fecha de expiración ≥ 30 días en el futuro
  - [ ] Renovación automática configurada (si Let's Encrypt, usar certbot con cron)

- [ ] **Reverse proxy (Nginx, Traefik, Caddy)**
  - [ ] Termina TLS en puerto 443
  - [ ] Reenvía a `api:8000` (interno Docker, no TLS)
  - [ ] Headers de seguridad: STS, X-Content-Type-Options, X-Frame-Options
  - [ ] CORS NO es "*" (restricción explícita si es necesario)

- [ ] **Test de TLS**
  - [ ] `curl -v https://api.tudominio.com/api/v1/whatsapp/webhook` NO da connection refused
  - [ ] `openssl s_client -connect api.tudominio.com:443` muestra "Verify return code: 0 (ok)"
  - [ ] Certificado es válido (no vencido, cadena completa)

---

## Fase 17: WhatsApp — Plantillas HSM

- [ ] **Plantilla creada en Meta**
  - [ ] Nombre: coincide con WHATSAPP_TEMPLATE_NAME (ej. `generic_template`)
  - [ ] Lenguaje: coincide con WHATSAPP_TEMPLATE_LANGUAGE (ej. `es`)
  - [ ] Categoría: `UTILITY` o similar (no MARKETING)
  - [ ] Contenido: ejemplo con variables {{1}}, {{2}} si aplica
  - [ ] Enviada a revisión

- [ ] **Plantilla aprobada**
  - [ ] Estado en Meta Dashboard: `APPROVED`
  - [ ] Verificar con:
    ```bash
    curl -G "https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/message_templates" \
      --data-urlencode "access_token=<WHATSAPP_TOKEN>" | jq '.data[].status'
    ```
  - [ ] Salida debe contener: `"APPROVED"`

- [ ] **Configuración en `.env`**
  - [ ] `WHATSAPP_TEMPLATE_NAME=generic_template` (o nombre real)
  - [ ] `WHATSAPP_TEMPLATE_LANGUAGE=es` (o lenguaje real)
  - [ ] `WHATSAPP_SESSION_WINDOW_HOURS=24` (ventana de Re-engagement)

---

## Fase 18: WhatsApp — Variables de Entorno Adicionales

- [ ] **Timeouts de envío**
  - [ ] `WHATSAPP_SEND_TIMEOUT_SECONDS=10` (timeout de conexión a Meta)
  - [ ] `WHATSAPP_SEND_MAX_RETRIES=3` (reintentos ante 429/5xx)
  - [ ] `WHATSAPP_SEND_BACKOFF_BASE_SECONDS=1` (espera inicial entre reintentos)

- [ ] **Versión de API**
  - [ ] `WHATSAPP_API_VERSION=v21.0` (o versión soportada)
  - [ ] Verificar compatibilidad en Meta API changelog

- [ ] **`.env.example` actualizado**
  - [ ] Contiene todos los placeholders de WhatsApp
  - [ ] Comentarios explican cada variable
  - [ ] Ningún valor real (CHECKPOINT C3)

---

## Fase 19: WhatsApp — Auditoría de Egress (ADR-006)

- [ ] **Egress acotado verificado**
  - [ ] `docker compose config | grep -A2 ia_internal | grep internal` devuelve `true`
  - [ ] Contenedor `ia` (Ollama) está SOLO en red `ia_internal` (sin egress)
  - [ ] Contenedor `api` está en ambas redes: `app` (egress) + `ia_internal` (interna)
  - [ ] Contenedor `wa_send_worker` está en ambas redes: `app` + `ia_internal`

- [ ] **Verificación de cero egress desde IA**
  - [ ] `docker exec crm_ia timeout 5 wget -T3 -qO- https://graph.facebook.com 2>&1`
  - [ ] Resultado: timeout o error de red (NO conexión exitosa)
  - [ ] Confirma que `ia` no puede alcanzar internet

- [ ] **Verificación de egress limitado desde `api` / `wa_send_worker`**
  - [ ] `docker exec crm_api sh -c "timeout 5 curl -s -I https://graph.facebook.com | head -1"`
  - [ ] Resultado: `HTTP/1.1 ...` u otra respuesta exitosa
  - [ ] Confirma que `api` SÍ puede alcanzar Meta

- [ ] **Check de módulos de código (allowlist por ruta)**
  - [ ] `bash backend/check-externos-backend.sh` devuelve "✓ APROBADO"
  - [ ] No hay imports de `graph_client` en módulos de IA
  - [ ] No hay imports de `AIClient` en módulos de transporte/WhatsApp

---

## Fase 20: WhatsApp — Workers y Colas

- [ ] **Workers de WhatsApp están en docker-compose.yml**
  - [ ] `whatsapp_inbound_worker`: consumidor de `wa:inbound` (SPEC-027)
  - [ ] `wa_send_worker`: consumidor de `wa:outbound` (SPEC-029)
  - [ ] Ambos con `depends_on: [db, redis]`
  - [ ] Variables de entorno correctas en docker-compose

- [ ] **Colas Redis persistentes**
  - [ ] Redis con `appendonly yes` (durabilidad)
  - [ ] Colas esperadas:
    - [ ] `wa:inbound` (webhooks entrantes)
    - [ ] `wa:outbound` (mensajes a enviar)
  - [ ] No hay jobs atascados: `docker compose exec redis redis-cli KEYS "wa:*" | wc -l`

- [ ] **Test de workers (sin deploy real)**
  - [ ] Simulador genera webhook: `python backend/tools/wa_webhook_simulator.py`
  - [ ] Webhook encolado en `wa:inbound`: `docker compose exec redis redis-cli LLEN wa:inbound:queue`
  - [ ] Worker procesa: logs muestran "whatsapp_webhook_event_processed"

---

## Fase 21: WhatsApp — Simulador de Webhook (SPEC-034)

- [ ] **Simulador descargado y funcional**
  - [ ] Archivo existe: `backend/tools/wa_webhook_simulator.py`
  - [ ] Dependencies disponibles: `pip install httpx`
  - [ ] Script compila: `python -m py_compile backend/tools/wa_webhook_simulator.py`

- [ ] **Test de firma HMAC**
  - [ ] Exportar app_secret: `export WHATSAPP_APP_SECRET=$(openssl rand -hex 32)`
  - [ ] Ejecutar simulador: `python backend/tools/wa_webhook_simulator.py`
  - [ ] Webhook acepta (200): firma HMAC es correcta
  - [ ] Verificar que firma no es hardcodeada (se calcula desde env)

- [ ] **Test de rechazo (firma inválida)**
  - [ ] Emitir webhook con firma falsa (manual o en test)
  - [ ] Webhook rechaza (401): validación de firma funciona
  - [ ] No procesa mensaje: criterio de aceptación SPEC-026 cumplido

- [ ] **Test de idempotencia (--duplicate flag)**
  - [ ] `python backend/tools/wa_webhook_simulator.py --duplicate`
  - [ ] Ambos webhooks aceptados (200)
  - [ ] Solo 1 mensaje en BD: deduplicación funciona (SPEC-027/ADR-007)

- [ ] **Test de statuses (--status flag)**
  - [ ] `python backend/tools/wa_webhook_simulator.py --status`
  - [ ] Sequence: sent → delivered → read
  - [ ] Statuses se concilian correctamente (SPEC-030)

---

## Fase 22: WhatsApp — OpenAPI y Documentación

- [ ] **EXAMPLES_OPENAPI.md actualizado**
  - [ ] Incluye ejemplos del webhook de WhatsApp (GET challenge, POST mensaje, POST status)
  - [ ] Colección de curl con placeholders (NO valores reales)
  - [ ] Muestran cómo probar en local vs. PROD

- [ ] **RUNBOOK_WHATSAPP.md completado**
  - [ ] Sección de alta de WABA
  - [ ] Configuración del webhook en Meta
  - [ ] Secret manager y variables de entorno
  - [ ] TLS del webhook
  - [ ] Plantillas HSM
  - [ ] Rotación de tokens
  - [ ] Simulador local
  - [ ] Troubleshooting de incidentes
  - [ ] Verificación de egress acotado

- [ ] **DEPLOYMENT_CHECKLIST.md extendido**
  - [ ] Referencia a DEPLOYMENT_CHECKLIST_WHATSAPP.md
  - [ ] Ítems de Fase 14–22 incluidos
  - [ ] Checkpoints C3 (secretos), C4 (criterios verificables), C6 (deploy sensible)

---

## Fase 23: WhatsApp — Rotación y Mantenimiento

- [ ] **Rotación de tokens documentada**
  - [ ] Procedimiento de renovación de `WHATSAPP_TOKEN` explícito
  - [ ] Calendarios: token expira en ~60 días, renovar antes
  - [ ] Secret manager actualizado durante rotación
  - [ ] Workers restarteados sin downtime significativo

- [ ] **Procedimiento de emergencia (token comprometido)**
  - [ ] Revocar token inmediatamente en Meta Dashboard
  - [ ] Generar uno nuevo
  - [ ] Actualizar en secret manager
  - [ ] Restart de `api` / `wa_send_worker`

---

## Fase 24: WhatsApp — Observabilidad y Monitoring

- [ ] **Logs disponibles**
  - [ ] `docker compose logs api --tail=50 | grep whatsapp`
  - [ ] `docker compose logs whatsapp_inbound_worker --tail=50`
  - [ ] `docker compose logs wa_send_worker --tail=50`

- [ ] **Métricas (si Prometheus disponible)**
  - [ ] Contador de webhooks recibidos
  - [ ] Contador de mensajes enviados
  - [ ] Latencia de procesamiento de webhook
  - [ ] Tasa de error (501, 503, etc.)

- [ ] **Alertas configuradas (recomendado)**
  - [ ] Alerta si webhook failures > X por minuto
  - [ ] Alerta si send failures > X por hora
  - [ ] Alerta si webhook signature rejections > 0 (anomalía)

---

## Fase 25: WhatsApp — Aprobación y Cierre (C6)

- [ ] **Lead ha revisado SPEC-034**
  - [ ] Todos los criterios de aceptación entienden
  - [ ] Aprobación explícita: "APROBADO SPEC-034"
  - [ ] Fecha de aprobación registrada

- [ ] **Plan de rollback comunicado**
  - [ ] Desactivar webhook en Meta (quitar suscripción)
  - [ ] No habrá reenvío de mensajes pendientes sin webhook
  - [ ] Tiempo de rollback: ~5 minutos

- [ ] **Ventana de mantenimiento**
  - [ ] Si hay webhook activo, notificar a clientes
  - [ ] Tiempo estimado de deploy: 10–15 minutos

---

## Resumen: Estado de WhatsApp

| Componente | Estado | Responsable |
|---|---|---|
| Secretos WABA (C3) | ⏳ | QUICKSILVER (secret manager) |
| Webhook HTTPS certificado | ⏳ | QUICKSILVER (proxy TLS) |
| Configuración en Meta | ⏳ | Operador manual (Meta Dashboard) |
| Plantilla HSM aprobada | ⏳ | Operador manual (Meta review) |
| Simulador local probado | ⏳ | QUICKSILVER (CI/local) |
| Idempotencia por wamid | ✓ | Backend (SPEC-027) |
| Egress acotado a Meta | ✓ | ADR-006 + firewall |
| Documentación (runbook, OpenAPI) | ⏳ | QUICKSILVER |
| Lead aprobación (C6) | ⏳ | Lead humano |

---

**Última actualización:** 2026-09-19 · **SPEC:** SPEC-034
**Referencias:** DEPLOYMENT_CHECKLIST.md, RUNBOOK_WHATSAPP.md, ADR-006, ADR-007
