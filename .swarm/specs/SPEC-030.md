# SPEC-030 — Statuses de entrega: `sent/delivered/read/failed` → actualización de `estado_entrega`

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: BACKEND · Fase: F5
- Deriva de: PLAN-003 (F5) · Clasificación: SENSIBLE (`.no-externo`) · ADR-007

## Objetivo

Procesar los callbacks de estado del webhook (`sent`/`delivered`/`read`/`failed`) y actualizar el `estado_entrega` del mensaje enviado, conciliando por el `wamid` de Meta, bajo RLS del tenant correspondiente.

## Contexto

Los statuses llegan por el mismo webhook (SPEC-026), validados por firma, y se enrutan/deduplican con el mismo patrón que la ingesta (SPEC-027). La conciliación usa el `wamid` persistido en el envío (SPEC-029). `messages.estado_entrega` (enviado/entregado/leído) ya existe desde SPEC-015; esta SPEC lo alimenta con los estados reales de Meta.

## Alcance

### IN
- Reconocer eventos de tipo `statuses` en el payload del webhook y encolarlos.
- Mapear `sent/delivered/read/failed` → `estado_entrega` del mensaje conciliado por `wamid`.
- Idempotencia: un status reentregado no corrompe el estado (transición monotónica/última-gana según diseño).
- Actualización bajo RLS del tenant dueño del mensaje.

### OUT
- Recepción/firma del webhook (SPEC-026); envío saliente (SPEC-029); indicadores SPA (SPEC-031).

## Dependencias
- Depende de SPEC-029 (mensaje enviado con `wamid` de Meta) y SPEC-026 (recepción del callback). Se ancla en ADR-007 (conciliación por `wamid`).

## Requisitos funcionales
- RF-01 Un callback `delivered`/`read` actualiza el `estado_entrega` del mensaje correcto.
- RF-02 Un callback `failed` marca el mensaje como fallido con motivo.
- RF-03 La conciliación se hace por `wamid` bajo RLS del tenant.

## Requisitos no funcionales
- RNF-04 Aislamiento multi-tenant: la actualización solo afecta al mensaje del tenant dueño.
- RNF-06 Observabilidad: contadores de entrega/error por estado.

## Criterios de aceptación (verificables)
- [ ] Un callback `sent`/`delivered`/`read` actualiza `estado_entrega` del mensaje conciliado por `wamid`.
- [ ] Un callback `failed` marca el mensaje como fallido con motivo registrado.
- [ ] Un status reentregado (duplicado) no corrompe el estado (idempotencia verificada).
- [ ] La actualización de estado NO cruza tenants (RLS); un status con `wamid` de otro tenant no altera el mensaje.
- [ ] Métricas/contadores reflejan entregas y errores por estado.

## Notas de seguridad (C2/C3)
- C2: no hay borrado físico; solo actualización de estado.
- C3: config SOLO en env; sin secretos en logs.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): procesa callbacks entrantes de Meta (tras el proxy TLS); no genera egress de inferencia. Conciliación 100% on-prem.

## Riesgos
- R-33 (idempotencia): status duplicado no corrompe estado; test de duplicado (SPEC-033).
- R-34 (fuga cross-tenant): conciliación por `wamid` bajo RLS.
- R-35 (errores Meta): estado `failed` reflejado + alertas.

## Checkpoints aplicables
- C2 (sin DELETE físico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-003).
