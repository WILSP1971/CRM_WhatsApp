# SPEC-015 — Canal WebChat propio: WebSocket bidireccional + Redis pub/sub

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, THOR, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: BACKEND/REALTIME · Fase: F3
- Deriva de: PLAN-002 (F3) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Implementar el canal real #1 (WebChat propio self-hosted): widget embebible + **WebSocket bidireccional**, persistencia de mensajes, **pub/sub por Redis** para push a la Bandeja y estados de entrega.

## Contexto

Fase F3 (SUP-22): primer canal real, 100% self-hosted, sin dependencia de Meta. Visitante ⇄ agente en tiempo real con persistencia en BD (SPEC-012) bajo RLS. La Bandeja de la SPA (Entregable #1) mostrará conversaciones reales tras SPEC-020. Base de CE-24.

## Alcance

### IN
- Widget WebChat embebible (cliente) que abre WebSocket con la API.
- Endpoint WebSocket bidireccional (recepción/envío) autenticado/scoped por tenant.
- Persistencia de cada mensaje (dirección, texto, `sentAt`, estado) en BD.
- Redis pub/sub para push del mensaje del visitante a la Bandeja del agente del tenant correcto.
- Estados de entrega del mensaje (enviado/entregado/leído) y reconexión.

### OUT
- Borrador RAG y human-in-the-loop (SPEC-017/019).
- Sentimiento del mensaje (SPEC-018).
- WhatsApp/IG/Messenger (Fase 3).
- Render de la Bandeja real en la SPA (SPEC-020).

## Dependencias
- Depende de SPEC-013 (auth/tenant) y SPEC-014 (modelo de mensajes/conversaciones). Prerequisito de SPEC-018, 019, 020.

## Requisitos funcionales
- RF-02 Un visitante escribe en el WebChat; el mensaje se persiste y aparece en tiempo real en la Bandeja del agente del tenant correspondiente.
- RF-03 El agente responde desde la Bandeja; el mensaje llega al visitante por WebSocket y queda persistido.
- RF El pub/sub enruta el mensaje solo al tenant correcto.
- RF Estados de entrega actualizados y reconexión soportada.

## Requisitos no funcionales
- RNF-05 Estado en BD/Redis (API stateless) para permitir réplicas.
- RNF-04 Latencia de entrega en tiempo real razonable (validada por THOR en SPEC-022).
- RNF-02 Aislamiento por tenant en el pub/sub y la persistencia.

## Criterios de aceptación (verificables)
- [ ] Un mensaje del visitante se persiste en BD y aparece en la Bandeja del agente del tenant correcto (e2e).
- [ ] La respuesta del agente llega al visitante por WebSocket y queda persistida (e2e).
- [ ] El pub/sub **no** entrega mensajes a agentes de otro tenant (aislamiento verificado).
- [ ] Los mensajes registran estado de entrega (enviado/entregado/leído).
- [ ] Tras caída/reconexión del socket, la conversación se recupera sin pérdida de mensajes persistidos.
- [ ] El WebSocket exige tenant autenticado; conexiones sin credencial válida se rechazan.

## Notas de seguridad (C2/C3)
- C2: conversaciones/mensajes con borrado lógico (Activo/Inactivo).
- C3: credenciales de Redis vía env.

## Restricción SENSIBLE aplicable
- WebChat propio self-hosted; ningún tercero procesa el contenido de los mensajes. WhatsApp/SIP solo como transporte a futuro, nunca inferencia.

## Riesgos
- R-23 (fuga cross-tenant en pub/sub): canales Redis namespaced por tenant + test.
- R-24 (latencia realtime): medición THOR (SPEC-022).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
