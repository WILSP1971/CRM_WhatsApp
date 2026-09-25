# SPEC-052 — Documentación, runbook de voz en vivo, simulador de llamada en vivo y deploy on-prem 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE, THOR · Prioridad: ALTA · Tipo: DOCS/DEPLOY/QA · Fase: F8
- Deriva de: PLAN-005 (F8, §9/§10) · Clasificación: SENSIBLE (`.no-externo`) · ADR-011/ADR-012
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Cerrar el Entregable #5 con: **runbook de voz en vivo** (integración del PBX de media/SIP, modelos STT/TTS, catálogo de intents, límite `C`, prioridad de GPU, política de degradación/modo bajo-cómputo) con placeholders y sin secretos; **contrato OpenAPI/AsyncAPI del `voice_gateway`** y del payload de escalación; un **simulador de llamada en vivo** verificable en local (**sin PBX real**) que inyecta audio es-CO ficticio y ejercita el bucle completo; y el **deploy on-prem** (Docker Compose) con **aprobación del Lead** (cambio sensible → notificación Telegram, C6).

## Contexto

Cierra la fase tras F6 (viabilidad, SPEC-050) y F7 (seguridad/persistencia, SPEC-051), replicando el patrón del simulador de #4 (SPEC-043, grabaciones) ahora para **media en vivo**. El simulador es imprescindible porque el piloto puede no tener PBX real (P-M): permite verificar todo el slice (declaración de voz sintética, STT streaming, NLU de catálogo, TTS/barge-in, escalación con contexto, persistencia) en local sin egress. El deploy on-prem reutiliza el `docker compose` de #4 con los servicios de voz añadidos (SPEC-044). El runbook documenta explícitamente la **política de degradación** (si ≤700 ms no se cumple → modo bajo-cómputo → recorte a IVR de comandos cortos) resultante de SPEC-050.

## Alcance

### IN
- **Runbook de voz en vivo:** integración del PBX de media/SIP (on-prem vs externo, allowlist ADR-011), elección/carga de modelos STT liviano y TTS Piper + banco de audios pregrabados, gestión del **catálogo de intents** (cómo revisar/versionar/reindexar), fijación del límite `C` (SPEC-050), mecanismo de prioridad de GPU (pausa/despriorización + VRAM reservada), y la **política de degradación** (modo bajo-cómputo / recorte). Con placeholders; sin secretos.
- **OpenAPI/AsyncAPI del `voice_gateway`** (sesión de media, eventos) y del **payload de escalación** (contrato de contexto de SPEC-049).
- **Simulador de llamada en vivo** (sin PBX real): inyecta audio es-CO ficticio bidireccional, ejercita declaración de voz sintética → STT streaming → NLU de catálogo → respuesta RAG/pregrabada → TTS → barge-in → escalación con contexto → persistencia; ejecutable en local, sin egress.
- **Deploy on-prem** (Docker Compose) reproducible sin internet de inferencia; runbook de arranque/rollback; verificación de que el flag OFF deja #1-#4 intactos.
- Actualización de la documentación de arquitectura con ADR-011/ADR-012 y los diagramas de topología/latencia (§3.2/§3.3).

### OUT
- Implementación de los servicios/medición (SPEC-044..051); despliegue del PBX real (fuera de alcance).

## Dependencias
- Depende de SPEC-050 (viabilidad/`C`/degradación) y SPEC-051 (seguridad/persistencia/retención). Reutiliza el patrón de simulador de SPEC-043. Se ancla en ADR-011/ADR-012. Cierra el Entregable #5.

## Requisitos funcionales
- RF-01 Existe el runbook de voz en vivo con PBX/modelos/catálogo/`C`/prioridad GPU/degradación, con placeholders y sin secretos.
- RF-02 Existe OpenAPI/AsyncAPI del `voice_gateway` y del payload de escalación.
- RF-03 El simulador de llamada en vivo ejercita el bucle completo en local, sin PBX real ni egress.
- RF-04 El deploy on-prem es reproducible con `docker compose up` sin internet de inferencia; rollback documentado.

## Requisitos no funcionales
- RNF-07 Todo reproducible on-prem; suites #1-#4 verdes; el flag OFF deja #1-#4 intactos.
- RNF-51 El simulador corre sin egress (voz/IA sin salida); no usa datos reales/PHI.

## Criterios de aceptación (verificables)
- [ ] El runbook cubre integración PBX de media/SIP, modelos STT/TTS, catálogo de intents, `C`, prioridad de GPU y política de degradación; sin secretos (placeholders).
- [ ] OpenAPI/AsyncAPI del `voice_gateway` y del payload de escalación disponibles y válidos.
- [ ] El simulador de llamada en vivo ejercita en local (sin PBX real): declaración de voz sintética → STT streaming → NLU catálogo → respuesta → TTS → barge-in → escalación con contexto → persistencia; sin egress.
- [ ] `docker compose up` levanta el stack de voz en vivo sin internet de inferencia; rollback documentado; flag OFF = #1-#4 intactos.
- [ ] La documentación de arquitectura referencia ADR-011/ADR-012 y los diagramas de topología/latencia.
- [ ] Deploy on-prem realizado con **aprobación explícita del Lead** + notificación Telegram (C6); suites #1-#4 verdes.

## Notas de seguridad (C2/C3)
- C3: runbook y `.env.example` con placeholders; ningún secreto real (credenciales PBX, claves TLS/cifrado) en repo/docs.
- C2: el deploy preserva el borrado lógico y la retención (SPEC-041/SPEC-051).
- C6: el deploy on-prem es cambio sensible → aprobación del Lead + notificación Telegram.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el simulador y el deploy corren 100% local; el simulador **sustituye al PBX real** sin abrir egress. Si el PBX es externo, la allowlist al host del PBX de media (ADR-011) se documenta y se activa solo con aprobación del Lead (C6).

## Riesgos
- R-61 (regresión #1-#4): deploy reversible (flag OFF); suites #1-#4 verdes; rollback documentado.
- R-51/R-52 (viabilidad/GPU): el runbook documenta la política de degradación y el `C` resultante de SPEC-050.
- R-54 (audio/TTS a terceros): el simulador corre sin egress; se verifica en SPEC-051.

## Checkpoints aplicables
- C2 (borrado lógico/retención). C3 (sin secretos, placeholders). C4 (criterios verificables). C6 (deploy on-prem sensible: aprobación + Telegram). C8 (origen PLAN-005).
