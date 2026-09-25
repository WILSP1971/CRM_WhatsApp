# SPEC-039 — Enriquecimiento IA local sobre la transcripción (reutiliza SPEC-017/018/019)

- Estado: EN_VERIFICACION · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, THOR, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: IA/BACKEND · Fase: F4
- Deriva de: PLAN-004 (F4, §3.1) · Clasificación: SENSIBLE (`.no-externo`) · ADR-005/ADR-009
- Aprobada por el Lead (aprobación en bloque SPEC-035..043 de PLAN-004). Implementada; pendiente de revisión (WOLVERINE) y pruebas (HAWKEYE).

## Objetivo

Conectar la transcripción persistida (SPEC-038) al **pipeline IA 100% local ya existente**: disparar **sentimiento** (SPEC-018), generar un **resumen** de la llamada y un **borrador de seguimiento RAG con ≥3 citas trazables** (SPEC-017), dejando todo listo para el **human-in-the-loop** (SPEC-019), **sin ninguna inferencia externa**.

## Contexto

El Entregable #2 ya tiene sentimiento LLM local (`sentiment_worker`), RAG local con ≥3 citas (`rag_ingest_worker`) y el human-in-the-loop atómico (SPEC-019); el Entregable #3 demostró que un canal nuevo (WhatsApp, SPEC-028) reutiliza ese pipeline tal cual. Esta SPEC hace lo análogo para la voz: la transcripción entra al mismo pipeline que un mensaje de texto, sin crear componentes de IA nuevos y sin salir de `ia_internal`. El resumen es la única adición de prompt sobre el pipeline existente (registrada en `prompt-lab/`, C8).

## Alcance

### IN
- Al persistir `call_transcript`, encolar **sentimiento** (SPEC-018) sobre el texto de la transcripción.
- Generar un **resumen** de la llamada (LLM local) y un **borrador de seguimiento RAG con ≥3 citas trazables** (SPEC-017) para esa llamada.
- Reutilizar contratos existentes (`sentimiento`/`sentimiento_score`, `rag.citations`); dejar resumen y borrador disponibles para el human-in-the-loop (SPEC-019).
- Registrar el prompt del resumen en `prompt-lab/` (C8).

### OUT
- Implementación de sentimiento/RAG/human-in-the-loop en sí (SPEC-017/018/019, existentes).
- Ficha de llamada en la SPA (SPEC-040); envío del borrador aprobado (fuera del slice de voz de esta fase).

## Dependencias
- Depende de SPEC-038 (transcripción persistida) y reutiliza SPEC-017/SPEC-018/SPEC-019. Se ancla en ADR-005 (IA sin egress) y ADR-009.

## Requisitos funcionales
- RF-01 La transcripción de una llamada recibe etiqueta de sentimiento (LLM local).
- RF-02 Se genera un resumen de la llamada (LLM local).
- RF-03 Se genera un borrador RAG con ≥3 citas trazables del tenant para esa llamada.
- RF-04 Resumen y borrador quedan listos para revisar/editar/aprobar (SPEC-019), sin envío autónomo.

## Requisitos no funcionales
- RNF-01 IA 100% local: sentimiento, resumen y RAG sin inferencia externa; IA sin egress (ADR-005/ADR-009).
- RNF-02 El borrador RAG mantiene el objetivo p95 ≤ 6 s (GPU) heredado del Entregable #2.

## Criterios de aceptación (verificables)
- [ ] La transcripción de una llamada queda con `sentimiento`/`sentimiento_score` asignados.
- [ ] Se produce un resumen de la llamada (LLM local) asociado a `call`.
- [ ] Se produce un borrador RAG con **≥3 citas** (`source`+`excerpt`+`similarityScore`) para esa llamada.
- [ ] Las citas apuntan a chunks reales del tenant (trazabilidad); recuperación bajo RLS del tenant.
- [ ] `check-externos-backend.sh` en verde; ninguna llamada a APIs de inferencia externas en el flujo.
- [ ] Resumen y borrador NO se envían automáticamente: quedan a la espera de aprobación (SPEC-019).
- [ ] Captura de red del flujo: cero salida pública desde IA/workers de IA/`stt_worker`.
- [ ] El prompt del resumen está registrado en `prompt-lab/` (C8).

## Notas de seguridad (C2/C3)
- C2: transcripción, resumen y borrador respetan borrado lógico.
- C3: config de colas/IA SOLO en env.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): TODA la IA (sentimiento, resumen, embeddings, RAG, generación) es on-prem en `ia_internal internal:true`; jamás alcanza internet ni el PBX (ADR-005/ADR-009). Nada se envía autónomamente: el human-in-the-loop (SPEC-019) es obligatorio antes de cualquier envío.

## Riesgos
- R-41 (fuga de egress hacia la IA): la IA sigue aislada (ADR-005/ADR-009); prueba de egress vacío (SPEC-042).
- R-48 (WER es-CO degrada enriquecimiento): el human-in-the-loop absorbe errores; el agente revisa/edita antes de enviar.
- R-42 (latencia RAG): heredado de SPEC-017; medición THOR (SPEC-042).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (prompt del resumen registrado). Origen PLAN-004.
