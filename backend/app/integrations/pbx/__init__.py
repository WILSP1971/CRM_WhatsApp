"""
Conector de ingesta de grabaciones telefónicas (PBX) — SPEC-037, ADR-007/ADR-010.

Este paquete contiene EXCLUSIVAMENTE el transporte de RECEPCIÓN (webhook que
recibe el fichero + metadatos, ACK rápido, encolado). Invariante de seguridad
(mismo criterio que `app/integrations/whatsapp/`, ADR-006/ADR-010):

- Este módulo RECIBE (egress cero); nunca descarga del host del PBX (eso,
  SOLO si el PBX es externo, es `app/services/telefonia/pbx_client.py` +
  `app/workers/recording_fetch_worker.py`, ADR-010).
- Jamás importa Ollama/`AIClient`/`app.services.rag` (transporte ≠ inferencia).
- No ejecuta SQL pesado ni dedup/resolución de tenant inline (eso es
  `app/workers/recording_ingest_worker.py`, SPEC-037, ADR-007): solo valida
  firma/verify_token + encola.
"""
