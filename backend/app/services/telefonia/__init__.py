"""
Servicio de telefonía (PBX) — módulo de transporte para descarga de grabaciones (SPEC-035, SPEC-037, ADR-010)

Este módulo SOLO contiene:
- Descarga de grabaciones desde el PBX (si externo, allowlist por ruta en check-externos-backend.sh, ADR-010)
- Validación de webhooks de grabaciones (firma HMAC-SHA256, ADR-010)
- Auditoría de acceso (quién descargó, cuándo, qué grabación)

PROHIBIDO en este módulo:
- Importar STT/IA (Ollama, RAG, etc.) — NUNCA inferencia, solo transporte (ADR-010)
- Comunicar con servicios de IA/inferencia en la nube — auditado en CI
- Acceder al almacén de audio del stt_worker — solo el worker escribe/borra

CHECKPOINT C3 (secretos):
- Credenciales del PBX (si externo): SOLO en env/secret manager, NUNCA en código
- WEBHOOK_VERIFY_TOKEN / WEBHOOK_SECRET: fail-fast si débiles/ausentes fuera de development
- Host del PBX: allowlist a nivel de host (firewall) + check-externos-backend.sh (prohibir fuera del módulo)

Implementado en SPEC-037:
- `audio_store.py`: almacenamiento/lectura del audio cifrado en reposo
  (Fernet + `AUDIO_ENCRYPTION_KEY`). Sin egress, sin importar httpx.
- `pbx_client.py`: descarga acotada del audio SOLO si `PBX_EXTERNAL_ENABLED`
  (ADR-010) — usado exclusivamente por `app/workers/recording_fetch_worker.py`.
  Inerte por defecto (SUP-42, PBX on-prem).
"""
