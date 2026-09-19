# SPEC-028 — Disparo del pipeline IA local sobre WhatsApp (reutiliza SPEC-017/018)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, THOR, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: IA/BACKEND · Fase: F3
- Deriva de: PLAN-003 (F3) · Clasificación: SENSIBLE (`.no-externo`) · ADR-005

## Objetivo

Conectar el mensaje entrante de WhatsApp (persistido en SPEC-027) al **pipeline IA 100% local ya existente**: disparar el análisis de **sentimiento** (SPEC-018) y dejar listo el **borrador RAG con ≥3 citas** (SPEC-017), reutilizando las colas/workers sin ninguna inferencia externa.

## Contexto

El Entregable #2 ya tiene sentimiento LLM local (`sentiment_worker`/`sentiment_queue`) y RAG local con ≥3 citas (`rag_ingest_worker`/`rag_queue`) más el human-in-the-loop (SPEC-019). Esta SPEC **reutiliza** esas piezas: el mensaje de WhatsApp entra al mismo pipeline que WebChat, sin crear componentes de IA nuevos y sin salir de `ia_internal`.

## Alcance

### IN
- Al persistir un mensaje `canal="whatsapp"` entrante, encolar sentimiento (SPEC-018) sobre ese mensaje.
- Encolar/solicitar la generación del borrador RAG con ≥3 citas trazables (SPEC-017) para ese mensaje.
- Reutilizar contratos existentes (`sentimiento`/`sentimiento_score`, `rag.citations`); dejar el borrador disponible para el human-in-the-loop (SPEC-019).

### OUT
- Implementación de sentimiento/RAG en sí (SPEC-017/018, ya existentes).
- Aprobación humana del borrador (SPEC-019, reutilizada) y envío (SPEC-029).

## Dependencias
- Depende de SPEC-027 (mensaje persistido) y reutiliza SPEC-017/SPEC-018/SPEC-019. Se ancla en ADR-005 (IA sin egress).

## Requisitos funcionales
- RF-01 Un mensaje entrante de WhatsApp recibe etiqueta de sentimiento (LLM local).
- RF-02 Se genera un borrador RAG con ≥3 citas trazables del tenant para ese mensaje.
- RF-03 El borrador queda listo para revisar/editar/aprobar (SPEC-019), sin envío autónomo.

## Requisitos no funcionales
- RNF-01 IA 100% local: sentimiento y RAG sin inferencia externa; IA sin egress (ADR-005).
- RNF-02 El borrador RAG mantiene el objetivo p95 ≤ 6 s (GPU) heredado del Entregable #2.

## Criterios de aceptación (verificables)
- [ ] Un mensaje `canal="whatsapp"` entrante queda con `sentimiento`/`sentimiento_score` asignados.
- [ ] Se produce un borrador RAG con **≥3 citas** (`source`+`excerpt`+`similarityScore`) para ese mensaje.
- [ ] Las citas apuntan a chunks reales del tenant (trazabilidad); recuperación bajo RLS del tenant.
- [ ] `check-externos-backend.sh` en verde; ninguna llamada a APIs de inferencia externas en el flujo.
- [ ] El borrador NO se envía automáticamente: queda a la espera de aprobación (SPEC-019).
- [ ] Captura de red del flujo: cero salida pública desde IA/workers de IA.

## Notas de seguridad (C2/C3)
- C2: el mensaje y el borrador respetan borrado lógico.
- C3: config de colas/IA SOLO en env.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): TODA la IA (sentimiento, embeddings, RAG, generación) es on-prem en `ia_internal internal:true`; jamás alcanza Meta ni internet (ADR-005). El transporte a Meta es solo para el envío aprobado (SPEC-029), no para inferencia.

## Riesgos
- R-31 (fuga de egress hacia la IA): la IA sigue aislada (ADR-005); prueba de egress vacío (SPEC-033).
- R-24 (latencia RAG): heredado de SPEC-017; medición THOR (SPEC-033).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-003).
