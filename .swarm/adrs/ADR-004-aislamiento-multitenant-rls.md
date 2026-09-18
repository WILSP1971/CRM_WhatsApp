# ADR-004 — Aislamiento multi-tenant con PostgreSQL Row Level Security (pool-model)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-002.md` (F1/F2, IN §1–§2, riesgo R-23, CE-22), `SPEC-012` (datos/RLS), `SPEC-013` (auth/tenant)

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

"OmniCore AI" es un CRM **multi-tenant**: varios clientes (tenants) comparten la plataforma, cada uno
con sus contactos, conversaciones, mensajes y corpus RAG. El aislamiento entre tenants es un requisito
de **privacidad y seguridad** duro: **ningún dato ni consulta puede cruzar de un tenant a otro**
(riesgo R-23, criterio CE-22, checkpoint de privacidad).

El slice #2 es de **escala piloto** (pocos tenants, ~10–50 agentes concurrentes, miles de mensajes/día,
un solo host con Docker Compose y `pgvector` — SUP-23 del PLAN-002). Se necesita un modelo de
aislamiento **robusto pero operativamente simple**, que se pueda **probar de forma automática** y que
el propio motor de base de datos **fuerce**, sin depender de que cada consulta de la aplicación filtre
correctamente por `tenant_id`.

---

## Decisión

Se adopta **PostgreSQL 16 con Row Level Security (RLS) en modelo de pool** (una sola base de datos,
políticas por `tenant_id`):

1. **Una BD compartida (pool-model):** todas las entidades transaccionales (tenants, usuarios,
   contactos, conversaciones, mensajes, documentos, chunks, embeddings) viven en la misma base y
   **llevan columna `tenant_id`** obligatoria.
2. **RLS forzado por el motor:** se habilitan políticas RLS (`ENABLE` + `FORCE ROW LEVEL SECURITY`)
   que filtran cada fila por el `tenant_id` de la sesión; el aislamiento **no** depende de la app.
3. **`tenant_id` de sesión por conexión:** el middleware de auth (SPEC-013), tras validar el JWT,
   **fija el `tenant_id`** en la sesión de BD (p. ej. `SET LOCAL app.tenant_id = ...`) que las
   políticas RLS usan como predicado. Cada request opera bajo el tenant autenticado.
4. **Borrado lógico (C2):** las entidades transaccionales usan Activo/Inactivo, nunca DELETE físico.
5. **Reservado para escala mayor:** schema-por-tenant o base-por-tenant se evaluarán en Fase 3+ si el
   volumen o requisitos de aislamiento físico lo justifican; **no** entran en el piloto.

---

## Alternativas consideradas

| Alternativa                                     | Por qué se descartó (para el piloto)                                                                                                                                                       |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Schema-por-tenant** (un esquema por cliente)  | Mejor aislamiento lógico, pero **más coste operativo**: migraciones y mantenimiento multiplicados por tenant, complejidad de conexión. Innecesario a escala piloto. **Reservado para escala mayor.** |
| **Base-por-tenant** (una BD física por cliente) | Aislamiento máximo, pero **coste operativo alto** (backups, migraciones, provisioning por cliente) y desperdicio de recursos en un solo host. **Reservado para escala mayor.**            |
| **Filtrado solo en la aplicación** (WHERE tenant_id) | Frágil: una consulta mal escrita filtra datos de otro tenant. **No lo fuerza el motor** → alto riesgo R-23. Rechazado; RLS es la defensa a nivel de datos.                        |
| **Discriminador sin RLS** (columna sin política) | Igual de frágil que el filtrado en app; sin garantía del motor. Rechazado.                                                                                                              |

---

## Consecuencias

**Pros**

- **Simplicidad operativa**: una sola BD, un set de migraciones, un `pgvector` compartido; adecuado al piloto.
- **Aislamiento forzado por el motor** (RLS `FORCE`): incluso una consulta de app sin filtro explícito
  no puede ver filas de otro tenant → mitiga R-23 de raíz.
- Compatible con `pgvector` en la misma base (los embeddings también llevan `tenant_id` y RLS).
- **Verificable automáticamente** (test cross-tenant que debe fallar), apto para CI y auditoría.

**Cons / mitigaciones**

- Un fallo de configuración RLS afectaría a todos los tenants → se mitiga con `FORCE`, `tenant_id`
  obligatorio en toda tabla y **pruebas automatizadas** (HAWKEYE) + revisión BLACK WIDOW (F1/F8).
- Aislamiento **lógico**, no físico (comparten instancia) → aceptable para datos de contacto/comercial
  (HABEAS DATA/GDPR-like, no PHI); el aislamiento físico se reserva para Fase 3+ si el Lead lo pide.
- Olvidar fijar el `tenant_id` de sesión abriría fuga → el middleware lo fija **siempre** y hay test
  que verifica que una sesión sin tenant no devuelve filas.

**Criterio de verificación (objetivo y verificable)**

- **Test cross-tenant que DEBE fallar por RLS** (CE-22): un usuario del tenant A intenta leer/escribir
  datos del tenant B y la operación **no devuelve nada / es denegada**; evidencia en CI (HAWKEYE).
- Toda tabla transaccional tiene columna `tenant_id NOT NULL` y política RLS activa (`FORCE`).
- Cada conexión/transacción **fija el `tenant_id` de sesión**; una sesión sin `tenant_id` no ve filas.
- Revisión de **BLACK WIDOW** confirma ausencia de fugas cross-tenant (F1/F8).

---

## Referencias

- `PLAN-002.md` — F1/F2, alcance IN §1–§2, riesgo **R-23**, criterio **CE-22**, DoD §3.
- `SPEC-012` — Modelo de datos multi-tenant, migraciones, **RLS por `tenant_id`**, borrado lógico, pgvector.
- `SPEC-013` — Autenticación y multi-tenant: inyección de `tenant_id` en la sesión que fuerza RLS.
- Relacionado: **ADR-005** (egress IA), **ADR-003** (IA local). Checkpoints C2 (borrado lógico), C3 (secretos).
