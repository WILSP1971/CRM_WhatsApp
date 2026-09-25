# SPEC-057 — Enriquecimiento IA local sobre la transcripción de la nota de voz (reutiliza SPEC-028/039 sin cambios de lógica) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, THOR, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: IA/BACKEND · Fase: F4
- Deriva de: PLAN-006 (F4, §2.7/§3.1) · Clasificación: SENSIBLE (`.no-externo`) · ADR-005/ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Confirmar y garantizar que, una vez el sink `message` (SPEC-056) escribe la transcripción en `Message.contenido`, **el `Message` de audio entra al MISMO camino de enriquecimiento IA local que cualquier WhatsApp de texto** (SPEC-028): sentimiento (SPEC-018) + resumen + **borrador RAG con ≥3 citas trazables** (SPEC-017) + **human-in-the-loop** (SPEC-019), con **respuesta SIEMPRE en TEXTO** (SPEC-029) y **sin ninguna inferencia externa**. El objetivo de diseño es **cero código nuevo de lógica de enriquecimiento**: solo el **disparo** del pipeline existente al completar la transcripción, tal como ya lo hacen `whatsapp_inbound_worker` (SPEC-028) y el sink `call` (SPEC-039).

## Contexto

El Entregable #2 tiene sentimiento LLM local (`sentiment_worker`), RAG local con ≥3 citas (`draft_service`/`rag_ingest_worker`) y el human-in-the-loop atómico (SPEC-019). El Entregable #3 demostró que un canal nuevo (WhatsApp texto, SPEC-028) reutiliza ese pipeline **tal cual** sobre `Message`. El Entregable #4 hizo lo análogo para la voz (SPEC-039), materializando la transcripción como `Message` antes de disparar el pipeline. **La nota de voz de WhatsApp llega a la misma situación: un `Message` con texto en una `Conversation`** — por diseño (ADR-013) es indistinguible de un WhatsApp de texto a partir de la transcripción. Por tanto el enriquecimiento **no requiere lógica nueva**: reutiliza el mismo disparo (`schedule_sentiment_analysis` + `generate_rag_draft` + `draft_review_service.create_draft`) que ya existe, en modo best-effort/degradado (R-21) que nunca revierte la transcripción persistida.

## Alcance

### IN
- Al quedar el `Message(tipo="audio")` con `contenido` poblado y `transcripcion_estado="ok"` (SPEC-056), **disparar el mismo pipeline** que SPEC-028 sobre ese `Message`: sentimiento (SPEC-018), resumen (si aplica al canal) y **borrador RAG con ≥3 citas** (SPEC-017), dejándolo listo para el **human-in-the-loop** (SPEC-019). **Respuesta SIEMPRE en TEXTO** por Graph API (SPEC-029) tras aprobación humana.
- **Punto de disparo:** se decide en implementación entre (a) que el sink `message` de SPEC-056 dispare el pipeline igual que hoy lo hace el sink `call` (`whatsapp_inbound_worker`/SPEC-039), o (b) que el `Message` actualizado reingrese al mismo disparo de SPEC-028. En ambos casos **la lógica de sentimiento/RAG/human-in-the-loop es la existente, sin cambios**.
- Reutilización de contratos existentes (`Message.sentimiento`/`sentimiento_score`, `rag.citations` con ≥3 citas trazables del tenant, borrador en estado `propuesto` de SPEC-019).
- Modo degradado (R-21, RNF-01 sin egress): si el LLM local no está disponible o no hay contexto para ≥3 citas, **no** se genera borrador/resumen; se loguea; la transcripción ya persistida (SPEC-056) **no** se ve afectada.

### OUT
- Implementación de sentimiento/RAG/human-in-the-loop en sí (SPEC-017/018/019, existentes) — **no se modifican**.
- Envío del borrador aprobado en sí (SPEC-029, reutilizada; la aprobación humana es obligatoria).
- **TTS de respuesta / respuesta en audio: FUERA** (P2/ADR-013) — no se implementa en ninguna forma en esta SPEC.
- SPA/badge (SPEC-059); retención (SPEC-058).

## Dependencias
- Depende de SPEC-056 (transcripción persistida en `Message.contenido`) y reutiliza SPEC-028 (disparo del pipeline sobre `Message`), SPEC-017/018/019 (enriquecimiento existente) y SPEC-029 (envío en texto con human-in-the-loop). Se ancla en ADR-005 (IA sin egress), ADR-009 y ADR-013 (respuesta solo texto).

## Requisitos funcionales
- RF-01 El `Message` de audio con texto recibe etiqueta de **sentimiento** (LLM local), igual que un WhatsApp de texto.
- RF-02 Se genera un **borrador RAG con ≥3 citas trazables** del tenant, listo para revisar/editar/aprobar (SPEC-019), sin envío autónomo.
- RF-03 La **respuesta es SIEMPRE en TEXTO** (SPEC-029) tras aprobación humana; **no** se genera ni envía audio (TTS fuera, P2/ADR-013).
- RF-04 El enriquecimiento **no introduce lógica nueva**: reutiliza el pipeline existente (SPEC-028/017/018/019).

## Requisitos no funcionales
- RNF-01 IA 100% local: sentimiento, resumen y RAG sin inferencia externa; IA sin egress (ADR-005/ADR-009).
- RNF-63 **Cero código nuevo de lógica de enriquecimiento**: solo el disparo del pipeline existente; el `Message` de audio transita el mismo camino que un `Message` de texto (indistinguible, ADR-013).
- RNF-02 El borrador RAG mantiene el objetivo p95 ≤ 6 s (GPU) heredado del Entregable #2.

## Criterios de aceptación (verificables)
- [ ] Un `Message(tipo="audio")` con transcripción queda con `sentimiento`/`sentimiento_score` asignados, igual que un WhatsApp de texto.
- [ ] Se produce un borrador RAG con **≥3 citas** (`source`+`excerpt`+`similarityScore`) trazables al tenant, en estado `propuesto` (no enviado).
- [ ] El borrador **NO** se envía automáticamente: espera aprobación humana (SPEC-019); tras aprobación, la respuesta se envía **en TEXTO** (SPEC-029).
- [ ] **No** se genera ni envía audio/TTS en ningún punto (verificación de ausencia de TTS, P2/ADR-013).
- [ ] `check-externos-backend.sh` en verde; captura de red: cero salida pública desde IA/workers de IA/`stt_worker`.
- [ ] El enriquecimiento del `Message` de audio y el de un WhatsApp de texto siguen el **mismo** camino (test que evidencia reutilización, sin lógica nueva de IA).

## Notas de seguridad (C2/C3)
- C2: transcripción, sentimiento, resumen y borrador respetan borrado lógico.
- C3: config de colas/IA SOLO en env.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): TODA la IA (sentimiento, resumen, embeddings, RAG, generación) es on-prem en `ia_internal internal:true`; jamás alcanza internet (ADR-005/ADR-009). Nada se envía autónomamente: el human-in-the-loop (SPEC-019) es obligatorio. **Respuesta solo en TEXTO** (TTS fuera, ADR-013).

## Riesgos
- R-61 (fuga de egress hacia la IA): la IA sigue aislada (ADR-005/ADR-009); prueba de egress vacío (SPEC-060).
- R-69/WER (transcripción imperfecta degrada enriquecimiento): el human-in-the-loop absorbe errores; el agente revisa/edita antes de enviar.
- R-42 (latencia RAG): heredado de SPEC-017; medición THOR (SPEC-060).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (secretos en env). C4 (criterios verificables). C8 (origen PLAN-006). (Sin prompt nuevo: se reutiliza el pipeline existente; el resumen, si se activa, reutiliza el prompt ya registrado de SPEC-039.)
