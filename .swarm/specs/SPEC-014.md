# SPEC-014 — API core REST + contrato OpenAPI

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: BACKEND/API · Fase: F3
- Deriva de: PLAN-002 (F3) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Exponer los endpoints REST de dominio (tenants, contactos, conversaciones, mensajes, documentos, contacto 360°) con validación y versionado, publicando un **contrato OpenAPI** navegable en `/docs` como fuente de verdad para la SPA.

## Contexto

Fase F3: base del canal real (SPEC-015) y de la integración con la SPA (SPEC-020). Los endpoints deben emitir las mismas formas de los contratos existentes (`tenants`, `conversations`, `messages[]`, `rag.citations`) o versionarlas de forma controlada. Todo endpoint opera bajo tenant autenticado (SPEC-013) y RLS (SPEC-012).

## Alcance

### IN
- CRUD tenant-aware de: `contacts`, `conversations`, `messages`, `documents`; lectura de `tenants`.
- Endpoint de contacto 360° (agrega contacto + conversaciones + historial).
- Validación de entrada/salida con esquemas (Pydantic); manejo de errores consistente.
- Versionado de API (p.ej. `/api/v1`); paginación y filtros básicos.
- OpenAPI publicado en `/docs` + colección de ejemplos.
- Formas de respuesta compatibles con `src/lib/types.ts` (o adaptador documentado).

### OUT
- WebSocket y pub/sub del WebChat (SPEC-015).
- Endpoints de IA/RAG/sentimiento/borrador (SPEC-016..019).
- Reemplazo de mocks en la SPA (SPEC-020).

## Dependencias
- Depende de SPEC-012 (esquema/RLS) y SPEC-013 (auth/tenant). Prerequisito de SPEC-015, 019, 020.

## Requisitos funcionales
- RF Endpoints CRUD tenant-aware para contactos/conversaciones/mensajes/documentos.
- RF Contacto 360° agrega datos del contacto y sus conversaciones.
- RF-08 Las respuestas respetan los contratos de tipo del Entregable #1 (o adaptador).
- RF-09 OpenAPI navegable en `/docs`.

## Requisitos no funcionales
- RNF-04 API REST no-IA con p95 ≤ 200 ms.
- RNF-07 OpenAPI como fuente de verdad; código tipado; validación estricta.
- Todo query bajo RLS; sin fugas cross-tenant.

## Criterios de aceptación (verificables)
- [ ] OpenAPI válido servido en `/docs` con todos los endpoints del alcance.
- [ ] Cada endpoint valida entrada y devuelve errores consistentes (4xx/5xx tipados).
- [ ] Respuestas compatibles con los contratos de `src/lib/types.ts` (o adaptador documentado).
- [ ] Un usuario del tenant A no obtiene registros del tenant B por ningún endpoint (RLS).
- [ ] Contacto 360° devuelve contacto + conversaciones + historial del mismo tenant.
- [ ] p95 de endpoints no-IA ≤ 200 ms en prueba de humo (validado formalmente en SPEC-022).
- [ ] Versionado `/api/v1` presente; paginación funcional.

## Notas de seguridad (C2/C3)
- C2: los listados excluyen registros `activo=false` por defecto (borrado lógico).
- C3: sin secretos en el código de la API; configuración por env.

## Restricción SENSIBLE aplicable
- Sin servicios externos de datos; toda la API opera on-prem contra PostgreSQL local.

## Riesgos
- R-23 (fuga cross-tenant): tests por endpoint + RLS.
- R-25 (romper contratos SPA): respetar `types.ts` o adaptador documentado.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
