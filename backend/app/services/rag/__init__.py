"""Pipeline RAG local — SPEC-017.

Submódulos:
- `chunking`: divide el texto de un documento en fragmentos configurables.
- `ingest_service`: orquesta chunking + embeddings (SPEC-016) + persistencia
  en `chunks`/`embeddings` (SPEC-012), con estados y reintento idempotente.
- `retrieval_service`: recuperación top-k por similitud coseno en `pgvector`,
  acotada al tenant de la sesión (RLS, ADR-004).
- `draft_service`: genera un borrador con el LLM local a partir del contexto
  recuperado, incluyendo citas trazables (`source`/`excerpt`/`similarityScore`).

CHECKPOINT SENSIBLE (.no-externo): todo el pipeline usa EXCLUSIVAMENTE
`app.services.ai_service.AIClient` (Ollama interno) para embeddings y
generación. Ningún módulo de este paquete importa un SDK de terceros ni abre
una conexión HTTP propia hacia un host externo.
"""
