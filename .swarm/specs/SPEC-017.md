# SPEC-017 — Pipeline RAG local: ingesta → chunking → embeddings → pgvector → borrador citado

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, THOR, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: IA/BACKEND · Fase: F4
- Deriva de: PLAN-002 (F4) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Implementar el pipeline RAG end-to-end 100% local: ingesta de documentos → chunking → **embeddings locales** → **pgvector** → recuperación top-k → **generación de borrador con LLM local** con **≥3 citas trazables** (`source` + `excerpt` + `similarityScore`).

## Contexto

Fase F4: usa el LLM y los embeddings locales de SPEC-016 y el esquema/pgvector de SPEC-012. La ingesta/indexado es **asíncrona** (colas Redis) para no bloquear con documentos grandes. Las citas respetan el contrato `rag.citations` del Entregable #1. Base de CE-23 (borrador con ≥3 citas trazables y p95 documentado). Prerequisito del borrador human-in-the-loop (SPEC-019).

## Alcance

### IN
- Ingesta de documentos (PDF/MD/DOCX/TXT) con estados (pendiente/indexado/error) por tenant.
- Chunking configurable (tamaño/solape) y persistencia de chunks.
- Generación de embeddings locales (SPEC-016) y almacenamiento en `pgvector` con índice (HNSW/IVF).
- Recuperación top-k por similitud, acotada, bajo RLS por tenant.
- Generación de borrador con el LLM local a partir del contexto recuperado.
- Citas trazables: cada borrador incluye **≥3 citas** con `source`, `excerpt` y `similarityScore`.
- Cola Redis para ingesta/indexado asíncrono con reintentos idempotentes.

### OUT
- Servidor de IA / embeddings en sí (SPEC-016).
- Sentimiento del mensaje (SPEC-018).
- Aprobación humana del borrador (SPEC-019).
- Render del panel RAG en la SPA (SPEC-020).

## Dependencias
- Depende de SPEC-016 (LLM + embeddings locales) y SPEC-012 (pgvector/esquema/RLS). Prerequisito de SPEC-019.

## Requisitos funcionales
- RF-06 Ingesta de un documento → chunking → embeddings → pgvector, con estado indexado.
- RF-07 Ante una pregunta, se recuperan los top-k chunks del tenant y se genera un borrador citado.
- RF Cada borrador incluye ≥3 citas con `source`, `excerpt` y `similarityScore`.
- RF La recuperación solo devuelve chunks del tenant autenticado (RLS).

## Requisitos no funcionales
- RNF-04 Latencia RAG **p95 ≤ 6 s** (GPU); degradación CPU documentada (medida formal en SPEC-022, THOR).
- RNF-02 Aislamiento por tenant en documentos/chunks/embeddings y recuperación.
- RNF-06 Ingesta asíncrona no bloqueante; estados y reintentos.

## Criterios de aceptación (verificables)
- [ ] Ingesta e2e: un documento se chunkea, embebe e indexa en pgvector con estado `indexado`.
- [ ] Ante una pregunta, el borrador generado incluye **≥3 citas** con `source` + `excerpt` + `similarityScore`.
- [ ] Las citas apuntan a chunks reales del documento ingerido (trazabilidad verificable).
- [ ] La recuperación de un tenant **no** devuelve chunks de otro tenant (RLS).
- [ ] p95 de la corrida RAG ≤ 6 s en GPU (o degradación CPU documentada) — verificado en SPEC-022.
- [ ] La ingesta de un documento grande no bloquea la API (procesada por cola Redis).
- [ ] Un documento con error de ingesta queda en estado `error` y admite reintento idempotente.

## Notas de seguridad (C2/C3)
- C2: documentos/chunks con borrado lógico (Activo/Inactivo); la recuperación excluye inactivos.
- C3: config de colas/embeddings SOLO en env.

## Restricción SENSIBLE aplicable
- Todo el pipeline (embeddings, recuperación, generación) es on-prem; ningún tercero ve documentos ni consultas. Cero inferencia externa (CE-21).

## Riesgos
- R-24 (latencia RAG): índice pgvector adecuado (HNSW/IVF), top-k acotado, caché de embeddings, prompts concisos.
- R-28 (ingesta bloqueante): colas Redis + estados + reintentos idempotentes.
- R-23 (fuga cross-tenant en recuperación): RLS + test cross-tenant (SPEC-022).

## Checkpoints aplicables
- C2 (borrado lógico documentos/chunks). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
