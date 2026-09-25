# SPEC-042 — Pruebas + carga (RTF/THOR) + observabilidad del canal de voz 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: HAWKEYE · Colaboran: THOR, BLACK PANTHER, BLACK WIDOW, WOLVERINE, CAPTAIN AMERICA · Prioridad: ALTA · Tipo: QA/PRUEBAS · Fase: F7
- Deriva de: PLAN-004 (F7) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-010
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Verificar el slice completo de voz con pruebas: **STT e2e** (segmentos + timestamps, cero terceros, WER documentado), **cross-tenant que DEBE fallar por RLS** (rol app no-superusuario, ADR-008), **idempotencia por `call_id`**, **prueba de egress** (STT/IA sin salida; si PBX externo, solo al host del PBX), **RTF del STT ≤ 1.0 en GPU bajo carga** (o degradación CPU documentada) con THOR, y **observabilidad** de cola/error por tenant.

## Contexto

Cierra la validación técnica del Entregable #4 usando el **simulador de grabaciones** (SPEC-043) cuando no haya PBX real. Reutiliza la infra de pruebas de los Entregables #2/#3 (pytest, Locust). Es la evidencia objetiva de CE-41..CE-45. El set de audios es-CO es **ficticio** (sin datos reales/PHI).

## Alcance

### IN
- Set de audios ficticios es-CO; test STT e2e: una grabación se transcribe con segmentos + timestamps y **cero** STT/TTS de terceros; **WER documentado** sobre el set.
- Test cross-tenant: una `call`/`call_transcript` de otro tenant **falla** por RLS (rol app no-superusuario, ADR-008); sin mapeo → descarte auditado.
- Test de idempotencia: reentrega por `call_id` no crea doble llamada/transcripción/borrador.
- Prueba de egress: intento de salida desde `stt_worker`/`ia`/workers de IA **falla**; (si PBX externo) `api`/`recording_fetch_worker` solo alcanzan el host del PBX.
- Carga/RTF del STT (THOR/Locust): **RTF ≤ 1.0 en GPU** bajo carga, o degradación CPU documentada; borrador RAG mantiene p95 ≤ 6 s (GPU).
- e2e del slice: ingesta → STT → enriquecimiento → ficha con human-in-the-loop.
- Observabilidad: métricas de RTF, tamaño/latencia de cola batch, tasa de error de transcripción, contadores por tenant.

### OUT
- Implementación del simulador en sí (SPEC-043); implementación de controles (SPEC-035..041).

## Dependencias
- Depende de SPEC-035..041 (slice completo) y del simulador (SPEC-043). Se ancla en ADR-009/ADR-010.

## Requisitos funcionales
- RF-01 Existe suite de tests de voz (STT e2e, cross-tenant, idempotencia, egress, carga/RTF, e2e).
- RF-02 La carga mide el RTF del STT bajo carga.
- RF-03 El e2e cubre el ciclo hasta el human-in-the-loop en la ficha de llamada.

## Requisitos no funcionales
- RNF-42 RTF del STT ≤ 1.0 en GPU verificado bajo carga (o degradación CPU documentada).
- RNF-41 Evidencia de cero audio/inferencia a terceros (prueba de egress vacío).
- RNF-07 Cobertura backend del canal de voz ≥ 80%; suites #1/#2/#3 verdes.

## Criterios de aceptación (verificables)
- [ ] STT e2e: una grabación es-CO ficticia se transcribe con segmentos + timestamps; **WER documentado** (CE-41).
- [ ] Test cross-tenant **falla** por RLS con el rol app no-superusuario (verde = el aislamiento se cumple) (CE-43).
- [ ] Test idempotencia: reentrega por `call_id` no crea doble llamada/transcripción/borrador (CE-43).
- [ ] Prueba de egress: salida desde `stt_worker`/`ia`/workers de IA **falla**; (si PBX externo) egress solo al host del PBX (CE-42).
- [ ] Carga/RTF: **RTF ≤ 1.0 en GPU** bajo carga (informe THOR) o degradación CPU documentada; borrador RAG p95 ≤ 6 s (GPU) (CE-45).
- [ ] e2e ingesta→STT→enriquecimiento→ficha con human-in-the-loop (nada se envía autónomamente).
- [ ] Cobertura backend de voz ≥ 80%; suites #1/#2/#3 verdes (sin regresión) (CE-45).
- [ ] Métricas de RTF/cola/error por tenant expuestas y verificadas.

## Notas de seguridad (C2/C3)
- C3: tests no exponen secretos; usan simulador/audios ficticios/placeholders.
- C2: tests verifican borrado lógico y purga por retención donde aplica.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (verifica egress): esta SPEC PRUEBA el invariante de la fase (ADR-009/ADR-010): STT/IA sin salida; audio nunca a terceros; (si PBX externo) transporte solo al host del PBX. La prueba de egress vacío es evidencia obligatoria del DoD.

## Riesgos
- R-41/R-42/R-45/R-46/R-47/R-48: cada uno cubierto por su test (egress, RTF, egress PBX, idempotencia, cross-tenant, WER).

## Checkpoints aplicables
- C2 (borrado lógico/purga). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-004).
