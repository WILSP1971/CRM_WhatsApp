# SPEC-061 — Documentación, runbook, simulador de nota de voz y deploy on-prem 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: DOCS/DEVOPS · Fase: F8
- Deriva de: PLAN-006 (F8) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Entregar la documentación operativa del slice de notas de voz de WhatsApp: **runbook** (descarga de media desde `graph.facebook.com` sin egress nuevo, límite de duración configurable, extensión de retención de mensajería, contrato del `destino` del `stt:jobs`, colocación de pesos Whisper por volumen), **notas de OpenAPI/parser** (reconocimiento de `type=="audio"`), y el **simulador de nota de voz** verificable en local sin egress; más el deploy on-prem (con aprobación del Lead, C6). Todos los documentos usan **placeholders, sin secretos** (C3).

## Contexto

Cierra el Entregable #5 tras F5/F7. Reutiliza el patrón de runbook/simulador de #3 (simulador de webhook firmado, SPEC-034) y #4 (simulador de grabaciones, SPEC-043). El simulador de nota de voz emite un evento de webhook de WhatsApp con `type=="audio"` (media ficticia OGG/Opus + `wamid`), incluyendo casos de **reentrega por `wamid`** y de **nota que excede el límite de duración**, validando el slice completo en local sin egress. El deploy on-prem es cambio sensible (C6, notificación Telegram). No hay egress nuevo que documentar como allowlist (se reutiliza `graph.facebook.com` de ADR-006); el runbook solo verifica el invariante.

## Alcance

### IN
- **Runbook operativo:** descarga de media de WhatsApp (host `graph.facebook.com` ya autorizado, sin egress nuevo, ADR-006; el `stt_worker`/IA nunca descarga), **límite de duración configurable** (default 10 min, env) + comportamiento de descarte amable, **extensión de retención** de mensajería (SPEC-058, mismo régimen que SPEC-041, default 30 días), **contrato del `destino`** de `stt:jobs` (`call:{id}` / `message:{id}`) y la garantía de no-regresión del sink `call`, colocación de pesos Whisper por volumen, rotación de secretos, cifrado del almacén, escalado de N `stt_worker`.
- **Notas de OpenAPI/parser:** el reconocimiento de `type=="audio"` en el webhook de WhatsApp (SPEC-055) y el campo `tipo` del `Message` en el DTO consumido por la SPA (SPEC-059); colección de ejemplos.
- **Simulador de nota de voz:** emite un evento de webhook de WhatsApp con `type=="audio"` (media ficticia OGG/Opus + metadatos + `wamid`), con casos de **reentrega por `wamid`** (idempotencia) y de **nota que excede el límite** (auto-respuesta), verificable en local **sin egress**.
- **Guía de deploy on-prem** (`docker compose up` + exposición HTTPS del webhook ya existente), con aprobación del Lead (C6, notificación Telegram).

### OUT
- Los tests que consumen el simulador (SPEC-060); implementación de controles (SPEC-053..059).

## Dependencias
- Depende de SPEC-058 (retención) y SPEC-060 (pruebas). Cierra el Entregable #5. Se ancla en ADR-009 y ADR-013.

## Requisitos funcionales
- RF-01 El runbook permite operar el slice (descarga de media, límite configurable, retención de mensajería, contrato `destino`, pesos Whisper, rotación, cifrado) sin secretos reales.
- RF-02 El simulador emite notas de voz ficticias verificables en local (incluye reentrega por `wamid` y nota que excede el límite).
- RF-03 Las notas de OpenAPI documentan el reconocimiento de `type=="audio"`; el deploy on-prem es reproducible.

## Requisitos no funcionales
- RNF-07 `docker compose up` reproducible sin internet de inferencia; solo el webhook expuesto por HTTPS (sin servicios nuevos expuestos).
- RNF-03 Documentación y simulador sin secretos; solo placeholders (C3).
- RNF-41 El simulador corre en local sin egress; no envía audio a terceros; documenta que la descarga sale solo a `graph.facebook.com` desde el módulo WhatsApp.

## Criterios de aceptación (verificables)
- [ ] El runbook cubre descarga de media (sin egress nuevo), límite de duración configurable, retención de mensajería (SPEC-058), contrato del `destino` de `stt:jobs`, pesos Whisper por volumen, rotación de secretos y cifrado del almacén, con placeholders.
- [ ] El simulador genera una nota de voz ficticia (`type=="audio"`) que el parser ingesta correctamente (transcrita e2e en local con el sink `message`).
- [ ] El simulador puede emitir una **reentrega por `wamid`** (prueba idempotencia) y una **nota que excede el límite** (prueba auto-respuesta/descarte).
- [ ] Las notas de OpenAPI/parser incluyen `type=="audio"` y el campo `tipo` del `Message`; colección de ejemplos disponible.
- [ ] Deploy on-prem reproducible con `docker compose up`; solo el path del webhook expuesto por HTTPS; sin internet de inferencia.
- [ ] Barrido: ningún secreto real ni PHI en runbook/OpenAPI/ejemplos/simulador.

## Notas de seguridad (C2/C3)
- C3: documentación y simulador con placeholders; secretos reales solo en env del operador.
- C6: deploy on-prem es cambio sensible → aprobación del Lead + notificación Telegram.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el simulador corre en local (sin egress); el deploy respeta el invariante (ADR-009/ADR-013): STT/IA sin salida, audio nunca a terceros, descarga solo a `graph.facebook.com` desde el módulo WhatsApp (sin egress nuevo), respuesta solo texto (sin TTS). Deploy requiere aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-61 (audio/inferencia a terceros): reafirmado en la guía de deploy; simulador sin egress.
- R-63/R-64 (cifrado/retención): documentados en el runbook (cifrado del almacén, retención de mensajería SPEC-058).
- R-62 (regresión sink `call`): el runbook documenta el contrato del `destino` y la garantía de no-regresión.

## Checkpoints aplicables
- C3 (sin secretos en docs). C4 (criterios verificables). C6 (deploy sensible: aprobación + Telegram). C8 (origen PLAN-006).
