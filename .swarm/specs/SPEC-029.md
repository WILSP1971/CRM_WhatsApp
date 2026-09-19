# SPEC-029 — Envío saliente por Graph API (transporte) + human-in-the-loop + ventana 24h/plantilla 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: CRÍTICA · Tipo: BACKEND/SEGURIDAD · Fase: F4
- Deriva de: PLAN-003 (F4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006

## Objetivo

Implementar el `wa_send_worker` con cliente **httpx** que envía a `graph.facebook.com` (transporte) el mensaje **aprobado por el agente** (SPEC-019), manejando la **ventana de servicio de 24 h** y **≥1 plantilla (HSM) utilitaria** fuera de ventana, con **rate-limit** hacia Meta y reintentos idempotentes; tokens desde secret manager. Nada se envía autónomamente.

## Contexto

Este es el borde de egress hacia Meta (ADR-006). Vive en el módulo del conector WhatsApp (única ruta con `graph.facebook.com` permitido en el allowlist de SPEC-024). El disparo es la **aprobación humana** (SPEC-019, transición atómica sin doble envío). Meta actúa solo como transporte: lo que sale es el texto ya aprobado, no una llamada de inferencia.

## Alcance

### IN
- `wa_send_worker` + cliente httpx SOLO a `graph.facebook.com` (transporte), en el módulo del conector.
- Disparo por aprobación del agente (SPEC-019); envío del mensaje aprobado; persistencia del `wamid` devuelto por Meta.
- Detección de la ventana de 24 h; dentro de ventana → texto libre; fuera → exigir/usar ≥1 plantilla HSM utilitaria.
- Rate-limit propio hacia Meta; reintentos con backoff idempotentes; manejo de errores (429/transitorios) → estado `failed`.
- Tokens (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`) desde env/secret manager; nunca en logs.

### OUT
- Procesamiento de callbacks de estado (SPEC-030).
- Aprobación humana en sí (SPEC-019, reutilizada) e indicadores SPA (SPEC-031).

## Dependencias
- Depende de SPEC-027 (mensaje persistido), SPEC-019 (aprobación) y SPEC-024 (egress acotado/allowlist/secretos). Puede avanzar en paralelo a SPEC-030. Se ancla en ADR-006.

## Requisitos funcionales
- RF-01 Un mensaje aprobado por el agente se envía por la Graph API y persiste el `wamid` de Meta.
- RF-02 Nada se envía sin aprobación humana (sin auto-respuesta).
- RF-03 Fuera de la ventana de 24 h se exige/usa una plantilla HSM aprobada.
- RF-04 Errores/429 de Meta → reintento con backoff idempotente; agotado → estado `failed`.

## Requisitos no funcionales
- RNF-01 Egress SOLO a `graph.facebook.com` desde este worker (transporte, no inferencia).
- RNF-03 Tokens en env/secret manager; nunca en logs; TLS hacia Meta.
- RNF-05 Rate-limit hacia Meta; reintentos idempotentes.

## Criterios de aceptación (verificables)
- [ ] Un mensaje aprobado (SPEC-019) se envía por `graph.facebook.com` y el `wamid` de Meta queda persistido.
- [ ] Sin aprobación humana NO hay envío (ningún path autónomo llama al envío).
- [ ] Dentro de ventana 24 h → texto libre aceptado; fuera de ventana sin plantilla → bloqueado con motivo.
- [ ] Con ≥1 plantilla HSM utilitaria configurada, el envío fuera de ventana usa la plantilla.
- [ ] Un 429/error transitorio se reintenta con backoff sin duplicar el envío (idempotente); agotado → `failed`.
- [ ] El cliente httpx solo alcanza `graph.facebook.com` (allowlist SPEC-024); otro dominio falla.
- [ ] Los logs no contienen `WHATSAPP_TOKEN`; secretos leídos de env con fail-fast.

## Notas de seguridad (C2/C3)
- C3: `WHATSAPP_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` SOLO en env/secret manager; jamás en repo/logs.
- C2: el mensaje enviado respeta borrado lógico; conciliación por `wamid`.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: EXCEPCIÓN ACOTADA (ADR-006): este worker es el ÚNICO (con `api`) autorizado a egress, y SOLO a `graph.facebook.com` como transporte del canal (no inferencia). Prohibido importar/llamar IA desde este módulo. Requiere aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-31 (fuga de egress hacia la IA): egress solo en este módulo; allowlist por ruta (SPEC-024); prueba de egress (SPEC-033).
- R-35 (rate limits/errores Meta): rate-limit propio + backoff idempotente + estado `failed` + alertas.
- R-36 (ventana 24 h vencida): detección de ventana + plantilla HSM; indicador SPA (SPEC-031).
- R-37 (tokens expuestos): secretos en env; redacción de logs; barrido BLACK WIDOW (SPEC-032).

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: egress a Meta + envío). C8 (origen PLAN-003).
