# SPEC-034 — Documentación, runbook del canal WhatsApp, simulador de webhook firmado y deploy on-prem

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: DOCS/DEVOPS · Fase: F9
- Deriva de: PLAN-003 (F9) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006

## Objetivo

Entregar la documentación operativa del canal: **runbook** (alta WABA, configuración de webhook/verify-token, secret manager, TLS, plantillas, rotación de token), OpenAPI del webhook, y —si no hay credenciales reales— el **SIMULADOR de webhook firmado** verificable en local; más el deploy on-prem (con aprobación del Lead).

## Contexto

Cierra el Entregable #3 tras F7/F8. Meta requiere alta de WABA, verificación del webhook (verify-token) y endpoint HTTPS; puede no haber credenciales en el piloto (SUP-33), por lo que se entrega un simulador de webhook firmado (HMAC) que permite validar todo el slice en local. Todos los documentos usan **placeholders, sin secretos** (C3).

## Alcance

### IN
- Runbook operativo: alta de WABA, configuración del webhook + `verify_token`, secret manager para las 4 vars, TLS del proxy, alta/uso de plantilla HSM, rotación de token.
- OpenAPI del/los endpoint(s) del webhook + colección de ejemplos.
- Simulador de webhook firmado (HMAC-SHA256) para GET challenge y POST (mensaje/duplicado/status) verificable en local.
- Guía de deploy on-prem (`docker compose up` + exposición HTTPS del webhook), con aprobación del Lead (C6).

### OUT
- Los tests que consumen el simulador (SPEC-033); implementación de controles de seguridad (SPEC-032).

## Dependencias
- Depende de SPEC-032 (seguridad) y SPEC-033 (pruebas). Cierra el Entregable #3. Se ancla en ADR-006.

## Requisitos funcionales
- RF-01 El runbook permite dar de alta el canal (WABA, webhook, verify-token, plantillas, rotación) sin secretos reales.
- RF-02 El simulador emite webhooks firmados (challenge, mensaje, duplicado, status) verificables en local.
- RF-03 OpenAPI documenta el webhook; el deploy on-prem es reproducible.

## Requisitos no funcionales
- RNF-07 `docker compose up` reproducible; solo el webhook expuesto por HTTPS.
- RNF-03 Documentación sin secretos; solo placeholders (C3).

## Criterios de aceptación (verificables)
- [ ] El runbook cubre alta WABA, webhook+verify-token, secret manager, TLS, plantilla HSM y rotación de token, con placeholders (sin secretos).
- [ ] El simulador genera un POST con firma HMAC válida que el webhook acepta (200) y uno inválido que rechaza (401).
- [ ] El simulador puede emitir un duplicado por `wamid` y un callback de status para probar idempotencia/conciliación.
- [ ] OpenAPI incluye el/los endpoint(s) del webhook; colección de ejemplos disponible.
- [ ] Deploy on-prem reproducible con `docker compose up`; solo el path del webhook expuesto por HTTPS.
- [ ] Barrido: ningún secreto real en runbook/OpenAPI/ejemplos.

## Notas de seguridad (C2/C3)
- C3: documentación y simulador con placeholders; secretos reales solo en env del operador.
- C6: deploy on-prem es cambio sensible → aprobación del Lead + notificación Telegram.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE: el simulador corre en local (sin egress); el deploy respeta la excepción de egress (ADR-006): IA sin salida, transporte solo a `graph.facebook.com`. Deploy requiere aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-37 (tokens expuestos): placeholders en docs; barrido antes de publicar.
- R-36 (ventana 24 h): documentada en runbook (plantilla HSM).
- R-31 (egress IA): reafirmado en la guía de deploy.

## Checkpoints aplicables
- C3 (sin secretos en docs). C4 (criterios verificables). C6 (deploy sensible: aprobación + Telegram). C8 (origen PLAN-003).
