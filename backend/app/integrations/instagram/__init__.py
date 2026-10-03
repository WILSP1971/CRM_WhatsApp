"""
Conector de Instagram Direct Messages (Meta Graph API).

SPEC-085 (F0): infraestructura, datos y secretos.
SPEC-086 (F1): webhook de recepción + parser puro.

Invariante de seguridad (espejo de ADR-006/SPEC-024, allowlist por ruta en
`check-externos-backend.sh`):
- Este módulo vive dentro de la allowlist permitida para egress a
  graph.facebook.com (aún sin transporte de envío real en esta fase).
- El módulo jamás importa Ollama ni servicios de IA (transporte ≠ inferencia).
"""
