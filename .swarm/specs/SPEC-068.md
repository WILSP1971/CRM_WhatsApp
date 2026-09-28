# SPEC-068 — ADR-014 (aprobación híbrida del audio + opt-in + no-persistencia + disclaimer + motor de F0) + modelo de datos aditivo (`respuesta_modo`/`tts_estado`/`audio_salida_ref` opcional) + limpieza de residuos `TTS_*` de config CPU-only 🔴 SENSIBLE

- Estado: CERRADA — `respuesta_modo`/`tts_estado`/`audio_salida_ref` añadidas a `rag_drafts` (migración `ff1eb9091a91`, verificada upgrade/downgrade/upgrade contra Postgres real); `TTS_MODE`/`TTS_VRAM_FRACTION` eliminados de `config.py` (sin consumidor real, residuos de la fase GPU archivada); `PIPER_VOICE` corregido a `es_ES-davefx-medium` (default anterior `es_CO-pablo-medium` no existe). Suite completa 684 passed / 1 fallo conocido y ajeno. Responsable: DOCTOR STRANGE (redacción de ADR); implementa CAPTAIN AMERICA (modelo de datos + config) · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: ADR/DATOS/BACKEND · Fase: F1
- Deriva de: PLAN-008 (F1, §2.IN.2/§2.IN.3, §3.5, §4, §11, R-87, CE-85/CE-87) · Clasificación: SENSIBLE (`.no-externo`) · ADR-013 (supersede §4)/ADR-012/ADR-009/ADR-006
- APROBADO SPEC-068 por el Lead (bloque PLAN-008) — 2026-09-28.

## Objetivo

Formalizar la **decisión arquitectónica** del Entregable #6 en **ADR-014** — cómo se **aprueba y envía** una respuesta de audio (TTS local) manteniendo el human-in-the-loop — y preparar el **modelo de datos aditivo/nullable** que lo soporta, **sin rediseñar** `Message`/`Conversation`/`rag_drafts` ni tocar el pipeline de #5. Además, **limpiar/reemplazar** los residuos de la fase GPU archivada (`TTS_MODE`, `PIPER_VOICE`, `TTS_VRAM_FRACTION`) en `backend/app/core/config.py` para que la configuración TTS sea **coherente con CPU-only** (R-87). El motor concreto queda fijado por **SPEC-067 (F0)**; el disclaimer de voz sintética ya está **decidido por el Lead: SÍ, marca ligera** (se formaliza, no se reabre).

## Contexto

Verificado en el modelo real:
- **`rag_drafts`** (`app/models/rag_draft.py`) es el borrador human-in-the-loop (SPEC-019): máquina de estados `propuesto → editado → aprobado → descartado`, con `content`/`content_original`, `approved_by`, `edited_by` y `sent_message_id` (se completa **solo al aprobar** — "nada se envía sin aprobación"). Es el **guion** que ancla la aprobación (Q1-C).
- **`messages`** (`app/models/message.py`) ya tiene, por SPEC-053/054/058, el discriminador `tipo` (`TIPOS_MENSAJE_VALIDOS = {"texto","audio"}`), `audio_ref`, `mime_type`, `transcripcion_estado`, `audio_duracion_seg`, `audio_purged_at`. Estos campos describen el audio **entrante** (nota de voz del cliente, #5); el audio **saliente** (TTS) es un vector distinto y **no** debe reutilizar `transcripcion_estado` (dos relojes distintos, ya documentado en el modelo).
- **`config.py` líneas 420–439** (verificado) contienen `tts_mode` (`"piper"`/`"prerecorded"`), `piper_voice` (`es_CO-pablo-medium`) y `tts_vram_fraction` (0.3) — **asumen GPU/VRAM** (ADR-011/ADR-012, fase archivada). `tts_vram_fraction` **carece de sentido en CPU-only**; `tts_mode` describe una interfaz de VoiceBot en vivo que ya no aplica; `piper_voice` puede reutilizarse como base pero **re-validado en CPU** por SPEC-067.
- **ADR-013 §4** aplazó explícitamente el "TTS de salida" ("posible Entregable #6"): este ADR lo **desbloquea/supersede**.

**Decisión de campos (a fijar sobre el modelo real, no inventar rígido):** los campos aditivos candidatos de PLAN-008 §3.5 se ubican donde corresponde: `respuesta_modo` (`"texto"` por defecto / `"audio"` opt-in) y `tts_estado` (`no_solicitado`/`generando`/`listo`/`error`, para la ruta "escuchar antes de enviar") son estado **del guion/respuesta** → naturalmente sobre `rag_drafts`; `audio_salida_ref` (opcional, solo si se persiste por auditoría) referencia el almacén cifrado (`audio_store.py`, SPEC-035), por defecto NULL/ausente. El nombre y la tabla exactos se confirman leyendo el modelo real al implementar; no se crea entidad nueva.

## Alcance

### IN
- **ADR-014** (archivo `.swarm/adrs/ADR-014-...md`), que decide: (a) invariante de aprobación anclado al **guion textual** (`rag_drafts`, Q1-C) con ruta opcional "escuchar antes de enviar" el clip bajo demanda; **ningún audio se envía sin aprobación humana** (del guion o del clip); (b) activación **opt-in** (Q2-A, default texto); (c) generación **en background, techo ≤5–10 s** (Q4-b), **CPU-only**, servicio aislado en `ia_internal` sin egress; (d) **motor = el validado por SPEC-067**; (e) **no persistir** el clip por defecto (herencia ADR-012 §5), y si se persiste por auditoría → cifrado + SPEC-041; (f) **disclaimer de voz sintética SÍ, marca ligera** (decisión vinculante del Lead). **Desbloquea/supersede** la parte "TTS de salida aplazado" de **ADR-013 §4**. Alternativas descartadas: las 4 de PLAN-008 §11.
- **Modelo de datos aditivo/nullable** (migración Alembic **aditiva**, head único, sin backfill destructivo): campos de estado de la respuesta de audio sobre `rag_drafts` — `respuesta_modo` (default lógico `"texto"`) y `tts_estado` opcional (`no_solicitado`/`generando`/`listo`/`error`) — con constantes de valores válidos documentadas en el modelo (patrón `ESTADOS_DRAFT_VALIDOS`/`TIPOS_MENSAJE_VALIDOS`); `audio_salida_ref` opcional (nullable, referencia opaca al almacén cifrado) **solo** para el caso de persistencia por auditoría, por defecto NULL. RLS/`TenantMixin`/`SoftDeleteMixin` heredados sin cambio. Los nombres/tabla exactos se confirman contra el modelo real antes de escribir la migración.
- **Limpieza/reemplazo de residuos `TTS_*` de config** (`config.py` líneas 420–439, CPU-only): **eliminar** `tts_vram_fraction` (sin sentido en CPU); **reemplazar/renombrar** `tts_mode` por una configuración coherente con TTS local asíncrono (o eliminarla si SPEC-067 la vuelve innecesaria); conservar/renombrar `piper_voice` **solo** si el motor de SPEC-067 la usa (re-validada en CPU), con comentario que referencie ADR-014/SPEC-067 y **elimine** las referencias a ADR-011/ADR-012 (GPU) obsoletas. Cambio documentado (qué se quita, qué se reemplaza, por qué) para el runbook de SPEC-072.

### OUT
- Prueba de viabilidad/decisión de motor (SPEC-067) — esta SPEC **consume** su salida.
- Servicio/worker TTS, cola `tts:jobs`, enganche al human-in-the-loop y subida por WhatsApp (SPEC-069).
- SPA/UX, feature-flag y la **implementación** del disclaimer (SPEC-070 — esta SPEC solo lo **decide**).
- Pruebas e2e/seguridad/no-regresión (SPEC-071) y docs/runbook/deploy (SPEC-072).
- Persistir el clip por defecto (ADR-012 §5: no se persiste salvo auditoría).

## Dependencias
- Depende de **SPEC-067** (motor elegido → registrado en ADR-014; **puerta previa**), de SPEC-012 (esquema/RLS), SPEC-019 (`rag_drafts`/máquina de estados) y SPEC-053 (patrón de columnas aditivas sobre `messages`). Se ancla en ADR-013 (supersede §4), ADR-012 (§4 disclaimer / §5 no-persistencia), ADR-009 (audio como PHI) y ADR-006 (transporte WhatsApp). **Prerequisito duro de SPEC-069/070/071/072.**

## Requisitos funcionales
- RF-01 ADR-014 queda redactado con las 6 decisiones (a–f) y las 4 alternativas descartadas, y declara que **desbloquea/supersede ADR-013 §4**.
- RF-02 El modelo de datos añade, de forma aditiva/nullable, el estado de la respuesta de audio (`respuesta_modo`, `tts_estado`) sobre `rag_drafts`, con constantes de valores válidos documentadas; `audio_salida_ref` opcional solo para auditoría.
- RF-03 La migración Alembic aplica (`upgrade`) y revierte (`downgrade`) limpio, con **head único**, sin backfill destructivo; el flujo de texto y el pipeline de #5 quedan intactos.
- RF-04 Se limpian/reemplazan los residuos `TTS_*` de `config.py` (elimina `tts_vram_fraction`; reemplaza/elimina `tts_mode`; re-valida/renombra `piper_voice` según SPEC-067), con comentarios que referencian ADR-014/SPEC-067 y sin dejar referencias GPU (ADR-011/ADR-012) vivas en ese bloque.

## Requisitos no funcionales
- RNF-64 Migración **aditiva no destructiva**; `respuesta_modo` default `"texto"` = comportamiento actual idéntico; suites #1–#6 verdes tras aplicarla.
- RNF-47 Aislamiento multi-tenant: los nuevos campos viven bajo la misma RLS efectiva (rol app no-superusuario, ADR-008); ningún tenant lee el estado/`audio_salida_ref` de otro.
- RNF-07 `alembic heads` devuelve un único head; sin ramas divergentes.
- RNF-CONFIG La configuración TTS resultante es coherente con CPU-only; no queda ninguna clave de VRAM/GPU en el bloque TTS.

## Criterios de aceptación (verificables)
- [ ] ADR-014 existe (`.swarm/adrs/ADR-014-...md`), en estado Aceptada tras aprobación del Lead, con las decisiones (a–f), las alternativas descartadas y la mención de supersede a ADR-013 §4.
- [ ] ADR-014 registra el **motor elegido por SPEC-067** (o su marcador de dependencia) y el **disclaimer = SÍ, marca ligera**.
- [ ] `alembic upgrade head` aplica la migración sin error; `downgrade` la revierte; `alembic heads` devuelve **un único head**.
- [ ] `rag_drafts` (o la tabla real confirmada) tiene `respuesta_modo` (default lógico `"texto"`) y `tts_estado` nullable con valores válidos documentados; `audio_salida_ref` nullable existe y por defecto es NULL.
- [ ] Un borrador existente sin opt-in queda con `respuesta_modo="texto"`: el flujo de texto (SPEC-029) y el pipeline #5 no cambian de comportamiento (test de no-regresión).
- [ ] `config.py` ya **no** contiene `tts_vram_fraction`; `tts_mode`/`piper_voice` quedan reemplazados/re-validados para CPU-only, sin referencias GPU (ADR-011/ADR-012) vivas en ese bloque; el arranque no rompe por la clave eliminada.
- [ ] RLS efectiva: una sesión de tenant A no lee los nuevos campos de tenant B (test cross-tenant que falla por RLS, verificado en SPEC-071).
- [ ] Suites #1–#6 verdes tras la migración y la limpieza de config (sin regresión).

## Notas de seguridad (C2/C3)
- C2: los nuevos campos heredan borrado lógico (`SoftDeleteMixin`); ningún DELETE físico; si `audio_salida_ref` se usa, la purga se rige por SPEC-041/058 (mismo régimen).
- C3: sin secretos en la migración/seed ni en config; la limpieza de `config.py` no introduce credenciales; `audio_salida_ref` es una referencia opaca, nunca un binario ni URL externa.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress): SPEC de decisión + datos + config; no introduce salidas externas. El disclaimer y la no-persistencia por defecto reducen la superficie SENSIBLE del vector de voz de salida. La subida del clip (cuando exista, SPEC-069) reutiliza `graph.facebook.com` (ADR-006) — **no es egress nuevo** y no se decide aquí.

## Riesgos
- R-87 (**residuos de config GPU** reutilizados por error en CPU): esta SPEC los limpia/reemplaza explícitamente; test de que `config.py` carga sin la clave eliminada y sin referencias GPU vivas. 
- R-82 (regresión de texto/#5/#4): todo aditivo/nullable, `respuesta_modo` default `"texto"`; migración con head único; suites verdes.
- R-85 (voz sintética/legal): resuelto en ADR-014 (disclaimer SÍ, marca ligera); implementación en SPEC-070 (CE-87).
- R-86 (retención/PHI del clip): por defecto no persistir; `audio_salida_ref` nullable, solo para auditoría con cifrado + SPEC-041.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C6 (ADR-014 es cambio arquitectónico sensible → notificación al aprobar/deploy). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
