# SPEC-043 — Documentación, runbook de voz, simulador de grabaciones y deploy on-prem 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: DOCS/DEVOPS · Fase: F8
- Deriva de: PLAN-004 (F8) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-010
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Entregar la documentación operativa del canal de voz: **runbook** (integración PBX/spool, descarga/modelos Whisper por volumen, política de retención/anonimización, rotación de secretos, cifrado del almacén), **OpenAPI del webhook** de grabaciones, y —si no hay PBX real (SUP-42)— el **SIMULADOR de grabaciones** verificable en local; más el deploy on-prem (con aprobación del Lead, C6).

## Contexto

Cierra el Entregable #4 tras F6/F7. Por SUP-42, puede no haber PBX en el piloto, por lo que se entrega un simulador de grabaciones (emite fichero WAV/OGG ficticio + metadatos con `call_id`, incluyendo casos de reentrega y de sin-mapeo-de-tenant) que valida todo el slice en local sin egress. Todos los documentos usan **placeholders, sin secretos** (C3). El deploy on-prem es cambio sensible (C6).

## Alcance

### IN
- Runbook operativo: integración PBX/spool (on-prem preferido; egress acotado si externo, ADR-010), colocación de pesos Whisper por volumen, política de retención/anonimización (SPEC-041), rotación de secretos, cifrado del almacén, escalado de N `stt_worker`.
- OpenAPI del/los endpoint(s) del webhook de grabaciones + colección de ejemplos.
- Simulador de grabaciones: emite audio ficticio + metadatos (`call_id`, número, dirección, duración, tenant), casos de reentrega por `call_id` y de sin-mapeo, verificable en local sin egress.
- Guía de deploy on-prem (`docker compose up` + exposición HTTPS del webhook), con aprobación del Lead (C6).

### OUT
- Los tests que consumen el simulador (SPEC-042); implementación de controles (SPEC-035..041).

## Dependencias
- Depende de SPEC-041 (retención/seguridad) y SPEC-042 (pruebas). Cierra el Entregable #4. Se ancla en ADR-009/ADR-010.

## Requisitos funcionales
- RF-01 El runbook permite operar el canal de voz (PBX/spool, modelos, retención, rotación, cifrado) sin secretos reales.
- RF-02 El simulador emite grabaciones ficticias verificables en local (incluye reentrega y sin-mapeo).
- RF-03 OpenAPI documenta el webhook; el deploy on-prem es reproducible.

## Requisitos no funcionales
- RNF-07 `docker compose up` reproducible sin internet de inferencia; solo el webhook expuesto por HTTPS.
- RNF-03 Documentación y simulador sin secretos; solo placeholders (C3).
- RNF-41 El simulador corre en local sin egress; no envía audio a terceros.

## Criterios de aceptación (verificables)
- [ ] El runbook cubre integración PBX/spool, pesos Whisper por volumen, retención/anonimización, rotación de secretos y cifrado del almacén, con placeholders (sin secretos).
- [ ] El simulador genera una grabación ficticia + metadatos que el conector ingesta correctamente (transcrita e2e en local).
- [ ] El simulador puede emitir una reentrega por `call_id` (prueba idempotencia) y un evento sin mapeo de tenant (prueba descarte auditado).
- [ ] OpenAPI incluye el/los endpoint(s) del webhook de grabaciones; colección de ejemplos disponible.
- [ ] Deploy on-prem reproducible con `docker compose up`; solo el path del webhook expuesto por HTTPS; sin internet de inferencia.
- [ ] Barrido: ningún secreto real ni PHI en runbook/OpenAPI/ejemplos/simulador.

## Notas de seguridad (C2/C3)
- C3: documentación y simulador con placeholders; secretos reales solo en env del operador.
- C6: deploy on-prem es cambio sensible → aprobación del Lead + notificación Telegram.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el simulador corre en local (sin egress); el deploy respeta el invariante (ADR-009/ADR-010): STT/IA sin salida, audio nunca a terceros, (si PBX externo) transporte solo al host del PBX. Deploy requiere aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-41 (audio/inferencia a terceros): reafirmado en la guía de deploy; simulador sin egress.
- R-43/R-44 (cifrado/retención): documentados en el runbook (cifrado del almacén, política de retención).
- R-45 (egress PBX): integración PBX documentada; on-prem preferido; allowlist si externo.

## Checkpoints aplicables
- C3 (sin secretos en docs). C4 (criterios verificables). C6 (deploy sensible: aprobación + Telegram). C8 (origen PLAN-004).
