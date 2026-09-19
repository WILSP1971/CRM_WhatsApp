"""
Conector de WhatsApp Business Cloud API (Meta).

SPEC-024 (F0): infraestructura y auditoría.
SPEC-026 (F2): webhook de recepción.
SPEC-029 (F4): envío saliente (transporte Graph API).

Invariante de seguridad (ADR-006, SPEC-024):
- Este módulo es la ÚNICA ruta permitida para egress a graph.facebook.com.
- Si graph.facebook.com aparece fuera de este módulo, check-externos-backend.sh FALLA.
- El módulo jamás importa Ollama ni servicios de IA (transporte ≠ inferencia).
"""
