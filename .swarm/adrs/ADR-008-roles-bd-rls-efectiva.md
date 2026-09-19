# ADR-008 — Modelo de roles de base de datos y RLS efectiva

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: hallazgo de 🐆 BLACK PANTHER en `SPEC-025`; complementa **ADR-004** (RLS multi-tenant)

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

El aislamiento multi-tenant de "OmniCore AI" se decidió con **PostgreSQL Row Level Security**
(`ENABLE` + `FORCE ROW LEVEL SECURITY`, **ADR-004**). Sin embargo, durante la revisión de `SPEC-025`,
🐆 **BLACK PANTHER** detectó que **el backend (api y workers) se conecta a PostgreSQL con el rol
`postgres`, que es SUPERUSUARIO**.

Esto invalida el aislamiento en runtime por un motivo del propio motor:

- **PostgreSQL NUNCA aplica RLS a superusuarios**, ni siquiera con `FORCE ROW LEVEL SECURITY`. Los
  superusuarios (y los roles con atributo `BYPASSRLS`) **omiten todas las políticas** de RLS.
- En consecuencia, el **Entregable #2** cree que aísla por RLS, pero **en runtime NO se aplica**: la
  app puede leer/escribir filas de cualquier tenant. El aislamiento "pasa" en los tests **solo porque
  esos tests corren con el mismo superusuario** → son **falsos positivos**.
- Como efecto colateral, la **resolución pre-tenant** de `whatsapp_accounts`
  (`phone_number_id → tenant_id`, necesaria en el webhook **antes** de fijar `app.tenant_id`, ADR-007)
  hoy "funciona" **por ese mismo accidente** (el superusuario ve todo), no por un diseño explícito.

Se necesita un modelo de roles que haga que **RLS se aplique de verdad** y que, aun así, permita la
resolución pre-tenant acotada del webhook sin abrir un bypass general.

---

## Decisión

1. **Rol de aplicación NO-superusuario y sin `BYPASSRLS`.** El runtime de la app (api, workers) se
   conecta con un rol **dedicado** (p. ej. `omnicore_app`) creado **`NOSUPERUSER NOBYPASSRLS NOCREATEDB
   NOCREATEROLE`**. Así RLS (`ENABLE` + `FORCE`) **se aplica realmente** a toda consulta de la app.
   El `DB_USER` de runtime pasa de `postgres` a `omnicore_app`.
2. **Rol privilegiado separado, solo para DDL/migraciones.** Un rol **owner** (p. ej. `omnicore_owner`,
   o el `postgres` actual) **propietario del esquema** se usa **exclusivamente** para Alembic/DDL y
   bootstrap; **nunca** para el runtime de la app. La app **no** puede ejecutar DDL.
3. **Resolución pre-tenant acotada por función `SECURITY DEFINER` de solo lectura.** Se define una
   función propiedad del rol privilegiado:

   ```sql
   -- Propietaria: omnicore_owner (rol privilegiado)
   CREATE OR REPLACE FUNCTION resolve_tenant_by_phone_number_id(p_phone_number_id text)
     RETURNS uuid
     LANGUAGE sql
     STABLE
     SECURITY DEFINER
     SET search_path = pg_catalog, public
   AS $$
     SELECT tenant_id
     FROM whatsapp_accounts
     WHERE phone_number_id = p_phone_number_id
       AND estado = 'Activo'
     LIMIT 1;
   $$;

   REVOKE ALL ON FUNCTION resolve_tenant_by_phone_number_id(text) FROM PUBLIC;
   GRANT EXECUTE ON FUNCTION resolve_tenant_by_phone_number_id(text) TO omnicore_app;
   ```

   Al ejecutarse con los privilegios del **owner**, la función resuelve `phone_number_id → tenant_id`
   **sin** que la app tenga que ver la tabla completa ni fijar `app.tenant_id` de antemano. Es
   **de solo lectura**, **acotada a una única entrada** (mapa de routing) y con `search_path` fijo para
   evitar secuestro. El webhook la invoca, obtiene el `tenant_id`, y **recién entonces** fija
   `app.tenant_id` (RLS FORCE) para el resto de la transacción (ADR-004/ADR-007).
4. **GRANTs mínimos.** Al rol de app se le otorga solo `SELECT/INSERT/UPDATE` sobre las tablas de datos
   (borrado lógico, C2), `EXECUTE` sobre la función de resolución, y **ningún** privilegio de DDL ni
   `BYPASSRLS`.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Seguir con superusuario `postgres` en runtime (status quo)** | **Inseguro:** RLS **nunca** se aplica a superusuarios; el aislamiento multi-tenant queda anulado y los tests son falsos positivos. Es exactamente el defecto detectado. Rechazado. |
| **Rol de app con `BYPASSRLS` dedicado** | Menos malo que superusuario, pero **abre un bypass general de RLS** para toda la app: cualquier consulta puede cruzar tenants. **Mayor superficie de fuga** que una función acotada de solo lectura. Rechazado. |
| **Tabla de plataforma `whatsapp_accounts` SIN RLS** (visible a todos) | Permitiría la resolución pre-tenant, pero **menos control**: la app vería todo el mapa de routing de todos los tenants y habría que razonar caso por caso qué tablas quedan "abiertas". La función `SECURITY DEFINER` acota el acceso a **una operación concreta**. Rechazada. |

La opción elegida (rol app sin bypass + función `SECURITY DEFINER` acotada) es la de **menor superficie**:
RLS se aplica a todo por defecto y solo se expone la resolución de routing estrictamente necesaria.

---

## Consecuencias

**Pros**

- **RLS se aplica de verdad en runtime** (ADR-004 deja de ser teórico): el motor fuerza el aislamiento
  aunque una consulta de la app olvide filtrar por `tenant_id`.
- **Tests que ejercen RLS con el rol NO-superusuario** dejan de ser falsos positivos.
- La resolución pre-tenant del webhook (ADR-007) queda **explícita y acotada**, sin bypass general.
- Separación de deberes: la app **no** puede hacer DDL; las migraciones viven en un rol privilegiado.

**Cons / mitigaciones**

- Hay que **crear roles y GRANTs en la inicialización de la BD** (`docker-entrypoint-initdb.d` o una
  migración/script de **bootstrap**) → se documenta en el runbook y se versiona.
- Cambiar `DB_USER` de runtime al rol de app y **mantener Alembic con el rol privilegiado** (dos
  cadenas de conexión: una para DDL/migraciones, otra para runtime) → variables de entorno separadas
  (secretos, C3).
- Los **tests de RLS deben correr con `omnicore_app`** (no con superusuario); de lo contrario siguen
  siendo falsos positivos → se ajusta la config de test (HAWKEYE) para conectar con el rol de app.
- La función `SECURITY DEFINER` es superficie sensible → se mitiga con `search_path` fijo,
  `REVOKE ... FROM PUBLIC`, solo lectura y una única consulta acotada.

**Impacto sobre otras decisiones**

- **Reafirma y complementa ADR-004** (RLS multi-tenant pool-model): ADR-004 definió `ENABLE`+`FORCE`,
  pero **solo es efectivo con un rol de app sin privilegios de bypass**; este ADR-008 aporta esa
  condición faltante.
- Se apoya en **ADR-007** (enrutado `phone_number_id → tenant_id`): la función de resolución es el
  mecanismo concreto que hace la resolución pre-tenant sin romper el aislamiento.

**Criterio de verificación (objetivo y verificable)**

1. **RLS real:** conectado con el **rol de app** (`omnicore_app`), un `SELECT` cross-tenant devuelve
   **0 filas** (no ve datos de otro tenant); el mismo test que hoy "pasa" con superusuario debe
   **cambiar de resultado** al usar el rol de app.
2. **Resolución pre-tenant:** `resolve_tenant_by_phone_number_id(<phone_number_id>)` ejecutada por el
   **rol de app**, **sin fijar `app.tenant_id`**, devuelve el **tenant correcto**.
3. **Sin fuga ni DDL:** el rol de app **no** puede leer filas de otro tenant **ni** ejecutar DDL
   (`CREATE/ALTER/DROP` fallan por permisos); verificado en CI (HAWKEYE) y revisado por BLACK WIDOW.

---

## Referencias

- Hallazgo de **BLACK PANTHER** en `SPEC-025` (backend conectado como superusuario `postgres`).
- **ADR-004** — Aislamiento multi-tenant con PostgreSQL RLS (pool-model): condición que este ADR completa.
- **ADR-007** — Idempotencia por `wamid` + enrutado `phone_number_id → tenant_id` (resolución pre-tenant).
- `SPEC-012` — Modelo de datos multi-tenant, migraciones (Alembic), RLS, `pgvector`.
- `SPEC-025` — `whatsapp_accounts` (routing) + `wamid` + RLS.
- Checkpoints: C2 (borrado lógico), C3 (secretos / cadenas de conexión separadas).
