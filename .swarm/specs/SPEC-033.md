# SPEC-033 — Pruebas + carga (THOR) + observabilidad del canal WhatsApp

- Estado: PROPUESTA · Responsable: HAWKEYE · Colaboran: THOR, BLACK PANTHER, BLACK WIDOW, WOLVERINE, CAPTAIN AMERICA · Prioridad: ALTA · Tipo: QA/PRUEBAS · Fase: F8
- Deriva de: PLAN-003 (F8) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006/ADR-007

## Objetivo

Verificar el slice completo del canal WhatsApp con pruebas: **cross-tenant que DEBE fallar por RLS**, **firma HMAC (válida/ inválida/ ausente)**, **idempotencia por `wamid`**, **prueba de egress** (IA sin salida; `api`/`wa_send_worker` solo a `graph.facebook.com`) y **carga del webhook** (p95 ACK ≤ 500 ms), con observabilidad de entrega/error.

## Contexto

Cierra la validación técnica del Entregable #3 usando el **simulador de webhook firmado** (SPEC-034) cuando no haya credenciales reales. Reutiliza la infra de pruebas del Entregable #2 (pytest, Locust). Es la evidencia objetiva de CE-31..CE-35.

## Alcance

### IN
- Test cross-tenant: un mensaje/status con `wamid`/`phone_number_id` de otro tenant **falla** por RLS/enrutado.
- Test de firma HMAC: firma válida → 200; inválida → 401; ausente → 401.
- Test de idempotencia: webhook duplicado por `wamid` NO crea mensaje/borrador/envío doble.
- Prueba de egress: intento de salida desde IA **falla**; `api`/`wa_send_worker` solo alcanzan `graph.facebook.com`.
- Carga del webhook (THOR/Locust): ACK 200 p95 ≤ 500 ms bajo carga.
- e2e cliente⇄agente (human-in-the-loop) por WhatsApp/simulador; statuses reflejados.
- Observabilidad: métricas de latencia webhook/envío, contadores de entrega/error.

### OUT
- Implementación del simulador en sí (SPEC-034); implementación de controles (SPEC-024/026/029).

## Dependencias
- Depende de SPEC-024..032 (slice completo) y del simulador (SPEC-034). Se ancla en ADR-006/ADR-007.

## Requisitos funcionales
- RF-01 Existe suite de tests del canal (firma, idempotencia, cross-tenant, egress, carga, e2e).
- RF-02 La carga del webhook mide p95 del ACK.
- RF-03 El e2e cubre el ciclo human-in-the-loop hasta statuses.

## Requisitos no funcionales
- RNF-02 p95 ACK webhook ≤ 500 ms verificado bajo carga.
- RNF-01 Evidencia de cero inferencia externa (prueba de egress).

## Criterios de aceptación (verificables)
- [ ] Test cross-tenant **falla** por RLS/enrutado (verde = el aislamiento se cumple).
- [ ] Test HMAC: válida → 200; inválida → 401; ausente → 401.
- [ ] Test idempotencia: webhook duplicado por `wamid` no crea doble mensaje/borrador/envío.
- [ ] Prueba de egress: salida desde IA **falla**; `api`/`wa_send_worker` solo alcanzan `graph.facebook.com`.
- [ ] Carga del webhook: **p95 ACK ≤ 500 ms** (informe THOR/Locust).
- [ ] e2e cliente⇄agente por WhatsApp/simulador con human-in-the-loop; statuses (`delivered`/`read`) reflejados en BD.
- [ ] Cobertura backend del canal ≥ 80%; suites #1/#2 verdes (sin regresión).

## Notas de seguridad (C2/C3)
- C3: tests no exponen secretos; usan simulador/placeholders.
- C2: tests verifican borrado lógico donde aplica.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (verifica egress): esta SPEC PRUEBA la excepción de egress (ADR-006): IA sin salida; transporte solo a `graph.facebook.com`. La prueba de egress es evidencia obligatoria del DoD.

## Riesgos
- R-31/R-32/R-33/R-34/R-38: cada uno cubierto por su test correspondiente (egress, HMAC, idempotencia, cross-tenant, latencia).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-003).
