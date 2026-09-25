# Prompt registrado — Resumen de llamada (canal de voz)

Registro canónico (CHECKPOINT C8, SPEC-039 — "Enriquecimiento IA local sobre
la transcripción"). Es la ÚNICA pieza de prompt NUEVA de la Fase 4 (Entregable
#4): el resto del enriquecimiento (sentimiento, borrador RAG con ≥3 citas)
REUTILIZA los prompts ya registrados/embebidos de SPEC-017/018 sin
modificación.

- Fecha: 2026-09-20
- Autor: CAPTAIN AMERICA
- Proyecto: /home/swarm/proyectos/CRM_WhatsApp (SENSIBLE, `.no-externo`)
- SPEC: SPEC-039 (PLAN-004, F4) — deriva de SPEC-038 (transcripción STT local)
- Componente: `backend/app/services/call_summary_service.py::generate_call_summary`
- Modelo: LLM local self-hosted vía Ollama (`AIClient.chat`, SPEC-016) —
  100% on-prem, `ia_internal internal:true`, sin egress (ADR-005/ADR-009)
- Objetivo: generar un resumen conciso (≤5 líneas) de una llamada de voz ya
  transcrita (`call_transcripts`, SPEC-036/038), para que el agente humano lo
  revise/edite antes de que forme parte de la ficha de la llamada (SPEC-040,
  fuera de alcance aquí) — human-in-the-loop (SPEC-019): el resumen generado
  NUNCA se marca como aprobado/definitivo automáticamente.

## Prompt de sistema (`system`)

```
Eres un asistente que redacta resúmenes de llamadas para un agente
humano de atención al cliente en español (es-CO). Dada la transcripción
completa de una llamada (posiblemente con turnos de agente y cliente
marcados), redacta un resumen breve y objetivo (máximo 5 líneas) que
incluya: el motivo de la llamada, los puntos clave tratados y, si
aplica, el siguiente paso acordado. Responde ÚNICAMENTE con el texto
del resumen, sin encabezados ni explicaciones adicionales. Si la
transcripción no tiene contenido suficiente para resumir, responde
exactamente: "Sin contenido suficiente para resumir."
```

## Prompt de usuario (`user`)

El texto completo de la transcripción de la llamada (concatenación de
`call_transcripts.segmentos[].texto`, en orden, SPEC-036/038), sin
preprocesamiento adicional.

## Parámetros de generación

- `temperature`: `0.2` (mismo criterio que `draft_service.generate_rag_draft`:
  texto determinista/objetivo, no creativo).
- `stream`: `false`.

## Modo degradado (R-21)

Si el LLM local no responde (`AIServiceUnavailableError`/
`AIServiceResponseError`) o la respuesta viene vacía, `generate_call_summary`
devuelve `summary=None` (`used_fallback=True`) — el resumen queda pendiente
de generar en un reintento posterior; la transcripción ya persistida por
`stt_worker` (SPEC-038) NUNCA se revierte ni se bloquea por esta falla.

## Trazabilidad

- Consumido exclusivamente por `app/workers/stt_worker.py`, tras persistir
  `call_transcripts` con éxito (mismo punto de enganche que SPEC-028 usa para
  disparar sentimiento/RAG desde `whatsapp_inbound_worker.py`).
- El resumen se persiste en `calls.resumen` (columna nueva, migración
  `e2a7c9f14b03`, SPEC-039) — nunca se envía ni se marca como aprobado
  automáticamente (SPEC-019, human-in-the-loop).
- Siguiente: ficha de llamada en la SPA (SPEC-040, fuera de alcance aquí).
