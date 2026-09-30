# PROMPT-009 — Onboarding multi-tenant self-service (alta de un cliente/negocio nuevo)

> Autor: 🧠 XAVIER (Professor X) — Estratega de Prompts (Nivel 1) · skill `optimizar-prompt`
> Fecha: 2026-09-29 · Proyecto: `/home/swarm/proyectos/CRM_WhatsApp`
> Clasificación: **SENSIBLE** (`.no-externo`) — el alta crea la raíz de aislamiento de datos personales de un cliente nuevo; un fallo aquí es una fuga cross-tenant.
> Marco aplicado: **C.R.A.F.T.** (Contexto · Rol · Acción · Formato · Tests)
> Destino: este prompt alimenta a 🔮 **DOCTOR STRANGE** para **PLAN-009** (NO genera SPECs por sí mismo).
> Contadores REALES (`.swarm/specs.json`): próximo plan libre = **PLAN-009** (⚠️ el campo `next_plan:8` está DESACTUALIZADO: PLAN-008 ya existe y está APROBADO con SPEC-067..072 CERRADAS), `next_spec: 73`, `next_adr: 15`. DOCTOR STRANGE debe corregir el contador `next_plan` a 10 al cerrar PLAN-009.
> ⚠️ **Puerta obligatoria:** este prompt NO es aprobación. Requiere PLAN-009 aprobado por el Lead y luego SPECs aprobadas antes de escribir código (CLAUDE.md del enjambre).

---

## 0. Resumen del encargo (una frase)

Habilitar que un **cliente/negocio nuevo (clínica u otro) pueda darse de alta en el CRM sin intervención manual de un desarrollador**, obteniendo su **propio tenant aislado** (sobre la RLS efectiva que ya funciona) y su **primer usuario administrador**, reemplazando el alta manual actual (scripts/SQL) por un **flujo de provisioning de tenant** con las garantías de aislamiento ya probadas en el proyecto.

Esta fase construye el **FLUJO DE ALTA que hoy no existe**. NO rediseña el aislamiento multi-tenant (ya existe y está probado): lo consume.

---

## 1. Contexto (verificado en el repo, no asumido)

### 1.1 Lo que YA existe (base sobre la que se construye)
- **Aislamiento multi-tenant REAL y probado:** RLS **ENABLE+FORCE** sobre `TENANT_SCOPED_TABLES` (`backend/app/db/rls.py:43`), con rol de aplicación `omnicore_app` **NOSUPERUSER NOBYPASSRLS** (ADR-004/ADR-008). El aislamiento de DATOS entre tenants **ya funciona y está probado extensivamente** (p. ej. `tests/test_rls_isolation.py`). Esta fase **NO lo rediseña**; solo añade el flujo de alta encima.
- **Modelo `Tenant` (raíz del aislamiento):** `backend/app/models/tenant.py` — columnas reales: `id` (uuid, `gen_random_uuid()`), `nombre` (str 255), `slug` (str 100, **UNIQUE**, index), + `TimestampMixin` + `SoftDeleteMixin` (borrado lógico C2, columna `activo`). `tenants` **NO** está en `TENANT_SCOPED_TABLES` (es la tabla raíz, sin `tenant_id` padre; ver `retention_service.py:108`).
- **Modelo `User`:** `backend/app/models/user.py` — `id`, `email` (str 255, index), `nombre`, `password_hash` (nullable, lo llena SPEC-013), `rol` (str 50, **default `"agente"`**), + `TenantMixin`/`TimestampMixin`/`SoftDeleteMixin`. Constraint **`uq_users_tenant_email`** (email único POR tenant, no global). No hay un rol `"admin"` reservado hoy: `rol` es texto libre con default `agente`.
- **Auth (SPEC-013):** login por **`tenant_slug` + email + password** (`backend/app/api/auth.py`), JWT con `tenant_id` embebido. `authenticate()` (`app/services/auth_service.py`) descubre el tenant por `tenant_slug` ANTES de existir JWT (usa `get_db` sin tenant fijado). Hashing de password ya resuelto en SPEC-013.
- **Lectura de tenant:** `backend/app/api/tenants.py` **SOLO** expone `GET /tenants/me` (el usuario lee su propio tenant vía `current_user.tenant_id`). **NO existe NINGÚN endpoint de creación de tenant.** Comentario explícito en el módulo: un listado global de tenants sería "una fuga cross-tenant/administrativa fuera de alcance".
- **Alta de tenant HOY = 100% manual:** vía `backend/app/db/seed.py` (`INSERT INTO tenants ... ON CONFLICT (slug) DO NOTHING`, ejecutado con el **rol owner de BD sin fijar `app.tenant_id`** — provisioning de plataforma, no operación de tenant autenticado) o `backend/loadtest/seed_loadtest_user.py`. Nunca self-service. El seed crea 2 tenants de referencia ("Clínica Demo Norte/Sur") — coherente con que cada fase previa asumió UN tenant de referencia ya existente para pruebas.

### 1.2 El canal WhatsApp: routing por-tenant SÍ, pero el token de envío es GLOBAL (⚠️ hallazgo crítico para el alcance — ver §7 Q2)
- **Recepción / routing entrante SÍ es por-tenant:** existe el modelo **`whatsapp_accounts`** (`backend/app/models/whatsapp_account.py`, en `TENANT_SCOPED_TABLES`, `rls.py:52`) que mapea `phone_number_id -> tenant_id` (SPEC-025, ADR-007). Cada número de WhatsApp Business dado de alta pertenece a un tenant; la resolución pre-tenant usa `resolve_tenant_by_phone_number_id()` (SECURITY DEFINER). Columnas: `phone_number_id` (UNIQUE global), `display_phone_number`, `etiqueta`. **Importante: NO guarda el token del WABA.**
- **Credencial de ENVÍO (Bearer del WABA) es GLOBAL de proceso:** `WHATSAPP_TOKEN` es una **env var única compartida** (`backend/app/core/config.py:176`), usada por `app/integrations/whatsapp/graph_client.py` para autenticar contra Graph API. Igual que `WHATSAPP_APP_SECRET` (HMAC del webhook, línea 156) y `WHATSAPP_VERIFY_TOKEN` (línea 161): **una sola app de Meta / un solo WABA para todo el proceso.** `WHATSAPP_PHONE_NUMBER_ID` (línea 187) es solo un fallback single-tenant; en multi-tenant el `phone_number_id` real sale de `whatsapp_accounts`.
- **Consecuencia para el onboarding (⚠️):** un tenant nuevo puede quedar **aislado en DATOS de inmediato** (RLS ya lo garantiza). Pero conectar **su propio número de WhatsApp Business** requiere hoy: (a) dar de alta su `phone_number_id` en `whatsapp_accounts`, y (b) que ese número cuelgue de la **misma app/WABA de Meta del proceso** (mismo `WHATSAPP_TOKEN`/`WHATSAPP_APP_SECRET` global). Un onboarding "self-service con su propio WABA independiente (app de Meta propia, tokens propios, Embedded Signup)" **NO es posible hoy sin trabajo grande adicional** (credenciales de WABA por-tenant, cifrado C3, verificación de negocio en Meta). Esto NO se asume resuelto — es la pregunta **§7 Q2**.

### 1.3 Señal de dominio a resolver con el Lead (§7 Q1)
- El correo del Lead es `@clinicacampbell.com.co` y el seed usa "Clínica Demo Norte/Sur". Esto **sugiere** (no confirma) que el CRM pudo nacer como herramienta de **un grupo de clínicas con varias sedes**, no necesariamente como SaaS vendido a terceros negocios. La diferencia entre "multi-sede de una organización" y "SaaS multi-cliente externo" **cambia radicalmente el diseño del alta** (autoregistro público vs alta administrativa interna). **No se asume: es §7 Q1.**

### 1.4 Invariantes del proyecto que rigen esta fase
- **SENSIBLE / `.no-externo`:** cero egress de inferencia; el alta no introduce llamadas externas nuevas de IA. Si el alta toca WhatsApp/Meta, el único transporte permitido es el ya autorizado (`graph.facebook.com`, ADR-006) — sin abrir nuevos egress.
- **RLS efectiva SIEMPRE:** cualquier código de alta que cree filas de un tenant nuevo debe respetar el modelo de roles (ADR-008). El **provisioning de la fila `tenants`** (tabla raíz) es una operación de plataforma que hoy corre con rol owner sin `app.tenant_id`; la fila del **primer usuario admin** (tabla scoped `users`) debe crearse fijando `app.tenant_id` del tenant recién creado (patrón RLS), o vía una función SECURITY DEFINER acotada — decisión de diseño de DOCTOR STRANGE, **prohibido bypass genérico con rol owner** (bug recurrente ya documentado en `retention_service`/`call_retention_service`).
- **Borrado lógico C2:** dar de baja un tenant = `activo=False`, nunca DELETE físico.
- **Contraseñas y secretos (C3):** el password del primer admin se guarda hasheado (reutiliza el hashing de SPEC-013); ningún secreto en claro en logs/DB.

---

## 2. Rol (quién debería resolverlo)

- 🔮 **DOCTOR STRANGE** — dueño de PLAN-009 y SPECs; traduce este prompt a plan/specs + posible ADR nuevo (candidato **ADR-015**) si el alta introduce una decisión estructural (p. ej. "cómo se provisiona la fila raíz `tenants` y el primer admin respetando RLS", o "modelo de credenciales WhatsApp por-tenant" si el Lead lo mete en alcance).
- ⚫ **BLACK PANTHER** — backend: servicio de provisioning de tenant + primer usuario admin, endpoint(s) de alta, respeto estricto de RLS/roles, unicidad de slug/email, transaccionalidad (tenant + admin en una sola unidad atómica).
- 🕶️ **BLACK WIDOW** — seguridad: superficie de abuso del alta (spam de tenants si es autoregistro público, rate-limit, verificación de email/anti-bot), aislamiento del tenant nuevo, cero fuga cross-tenant, manejo de secretos.
- 🕷️ **SPIDER-MAN** / 🔴 **DAREDEVIL** — UX/frontend del alta (formulario de registro público **o** panel admin interno, según §7 Q1) — solo si el Lead elige una opción con UI.
- 🦅 **HAWKEYE** — pruebas: alta feliz, colisión de slug/email, aislamiento del tenant nuevo (RLS cross-tenant), idempotencia, cero regresión del login/auth existente.
- ⚡ **QUICKSILVER** — docs/runbook del nuevo flujo de alta + deprecación (o no) del alta por seed/SQL.

---

## 3. Acción (verbo único y medible)

**Diseñar** (PLAN-009 + SPECs, NO implementar aún) un **flujo de alta de un tenant nuevo + su primer usuario administrador**, self-service en el grado que decida el Lead (§7 Q1), que:
1. cree la fila raíz `tenants` (nombre + slug único, `activo`) de forma atómica junto con su primer usuario admin (email único por tenant, password hasheado, rol de administrador);
2. deje el tenant **aislado por RLS desde el primer commit** (reutilizando la infraestructura ADR-004/ADR-008, sin rediseñarla);
3. permita al primer admin **hacer login inmediatamente** con el flujo existente (`tenant_slug` + email + password, SPEC-013) — o tras verificación/activación si el Lead lo pide (§7 Q3);
4. sea **aditivo y sin regresión**: no rompe `GET /tenants/me`, ni el login, ni el alta por seed que siguen usando las fases previas para sus tenants de referencia.

Sub-acciones orientativas (sujetas a §7):
- Definir **quién puede invocar el alta** (§7 Q1) y la superficie (endpoint público / endpoint admin protegido / CLI interno).
- Definir el **rol del primer usuario** (introducir un `rol="admin"` explícito vs el default `"agente"` actual — hoy no hay rol admin reservado).
- Decidir **generación/validación de slug** (derivado del nombre, colisiones, reservados).
- Decidir la relación con **`whatsapp_accounts`** en el alta (§7 Q2): ¿el alta crea un tenant "sin canal" y el número se conecta después por separado (recomendado), o entra en alcance conectar WhatsApp en el mismo flujo?
- Decidir **verificación de email / activación** (§7 Q3) y **planes/límites** (§7 Q4).

---

## 4. Restricciones (invariantes duros — no negociables)

- **NO rediseñar el aislamiento multi-tenant.** RLS ENABLE+FORCE, rol `omnicore_app` NOSUPERUSER NOBYPASSRLS, `TENANT_SCOPED_TABLES` y ADR-004/008 se **consumen tal cual**. Esta fase construye el alta, no el aislamiento.
- **Aislamiento del tenant nuevo garantizado desde el commit inicial.** Test cross-tenant obligatorio: un tenant recién creado no ve ni es visto por otros.
- **Prohibido bypass genérico de RLS con rol owner** para operaciones de tenant. El provisioning de la fila raíz `tenants` (operación de plataforma) puede correr con privilegio elevado acotado (como el seed hoy), pero la creación del primer usuario (`users`, tabla scoped) respeta RLS/`app.tenant_id` o usa una función SECURITY DEFINER acotada — nunca un bypass general.
- **Atomicidad tenant+admin.** Crear un tenant sin admin (o al revés) deja el sistema en estado inconsistente; el alta es una sola transacción "todo o nada".
- **Unicidad respetada:** `slug` UNIQUE global en `tenants`; email único POR tenant (`uq_users_tenant_email`). Colisiones deben responder error tipado, no 500.
- **Secretos (C3):** password del admin hasheado (hashing de SPEC-013); ningún secreto en claro en logs.
- **Sin egress nuevo.** El alta no introduce llamadas externas. Si toca verificación de email, el mecanismo (SMTP/servicio) es una decisión del Lead (§7 Q3) y debe respetar la política SENSIBLE.
- **Aditivo / cero regresión.** `GET /tenants/me`, login (SPEC-013), seed y las fases #1-#6 siguen funcionando sin cambios de comportamiento.
- **Migración de tenants existentes: FUERA.** Los tenants ya creados por seed/SQL siguen como están; esta fase es solo el flujo de alta NUEVO hacia adelante.

---

## 5. Formato de salida esperado (lo que DOCTOR STRANGE debe producir con este prompt)

1. **`.swarm/PLAN-009.md`** — plan profesional: objetivo, alcance IN/OUT explícito, fases, entregables, riesgos (top: superficie de abuso si es autoregistro público; fuga cross-tenant en el alta), criterios de éxito (CE), DoD. Debe **incorporar las respuestas del Lead a §7** antes de cerrarse.
2. **ADR candidato (ADR-015)** si aplica — p. ej. "Provisioning de la fila raíz `tenants` + primer usuario admin respetando RLS efectiva" y/o "modelo de quién puede crear tenants". Solo si introduce una decisión estructural nueva.
3. **Set de SPECs** (a partir de `next_spec: 73`) derivadas del plan aprobado — NO en este paso.
4. Corregir el contador `next_plan` en `.swarm/specs.json` (está en 8, debe reflejar que PLAN-009 se consume).
5. Todo en español, clasificación SENSIBLE en el encabezado, coherente con el estilo de PLAN-006/007/008 y ADRs previos.

---

## 6. Criterios de éxito (cómo se sabrá que el resultado es correcto)

- **CE-1 (alta funcional sin desarrollador):** un cliente/negocio nuevo se da de alta (en el grado decidido en §7 Q1) y obtiene tenant + primer admin sin que un desarrollador toque SQL/scripts.
- **CE-2 (aislamiento desde el primer commit):** el tenant recién creado está aislado por RLS; test cross-tenant verifica que no ve ni es visto por otros tenants.
- **CE-3 (login inmediato o tras activación):** el primer admin puede autenticarse con el flujo existente (`tenant_slug`+email+password) inmediatamente o tras la activación definida en §7 Q3.
- **CE-4 (atomicidad + unicidad):** colisión de slug o email devuelve error tipado (no 500); un fallo a mitad del alta no deja tenant huérfano sin admin ni viceversa.
- **CE-5 (sin bypass RLS / secretos seguros):** ninguna operación de tenant usa bypass genérico de owner; el password del admin queda hasheado; cero secretos en logs.
- **CE-6 (cero regresión):** login, `GET /tenants/me`, seed y fases #1-#6 siguen pasando sus suites sin modificar asserts.
- **CE-7 (alcance acotado):** lo listado como OUT (§8) no aparece implementado salvo que el Lead lo pida en §7.

---

## 7. Preguntas abiertas para el Lead (máx. 4 — con opciones concretas y trade-offs)

> Estas 4 decisiones son las que DOCTOR STRANGE necesita para cerrar PLAN-009. Sin ellas, el plan queda bloqueado.

### Q1 — ¿QUIÉN puede crear un tenant, y cuál es el caso de uso real? (la pregunta que define toda la fase)
Antes de las opciones, una pregunta de fondo que las condiciona: **¿el caso de uso real es (i) UN grupo de clínicas/organización con varias sedes** (multi-sede interno — el dominio `clinicacampbell.com.co` y el seed "Norte/Sur" lo sugieren), **o (ii) SaaS vendido a terceros negocios externos** que se registran solos? La respuesta cambia el diseño por completo.
- **Opción A — Autoregistro público** (formulario abierto: cualquiera se da de alta, típico SaaS B2B).
  - *Pros:* crecimiento sin fricción; escala a muchos clientes externos sin intervención.
  - *Contras:* **abre superficie de abuso** (spam de tenants, bots) → obliga a verificación de email + rate-limit + anti-bot (§7 Q3); solo tiene sentido si el caso es (ii) SaaS externo.
- **Opción B — Alta administrativa interna** (solo un admin de plataforma crea tenants, por invitación/panel admin; sin autoregistro público).
  - *Pros:* control total, mínima superficie de abuso; encaja con caso (i) multi-sede o SaaS con ventas asistidas; requiere introducir el concepto de "admin de plataforma" (rol/superusuario de la app, hoy inexistente).
  - *Contras:* no es "self-service" para el cliente final (lo hace el equipo interno); necesita definir quién es el admin de plataforma y cómo se autentica.
- **Opción C — API/CLI interno para ventas/operaciones** (sin UI pública; el equipo interno ejecuta el alta programáticamente, mejora del seed actual).
  - *Pros:* mínimo esfuerzo de UX; formaliza y hace seguro el alta que hoy es SQL manual; buen primer slice.
  - *Contras:* sigue requiriendo intervención del equipo (no del cliente); no es autoservicio del cliente final.
- *Recomendación XAVIER (no vinculante):* si el caso real es (i) multi-sede de un grupo de clínicas → **Opción B o C**. Si es (ii) SaaS externo genuino → **Opción A** con las salvaguardas de Q3. **Decisión del Lead.**

### Q2 — ¿Qué pasa con el CANAL WhatsApp al crear un tenant nuevo? (hallazgo verificado: routing por-tenant SÍ, pero token de envío GLOBAL)
Evidencia (§1.2): `whatsapp_accounts` mapea `phone_number_id->tenant_id` por-tenant, PERO `WHATSAPP_TOKEN`/`WHATSAPP_APP_SECRET`/`WHATSAPP_VERIFY_TOKEN` son **env vars GLOBALES de proceso = una sola app/WABA de Meta para todos**.
- **Opción A — Tenant se crea SIN canal; WhatsApp se conecta después, aparte** (esta fase = solo alta de tenant + admin; el número se da de alta en `whatsapp_accounts` en un paso/fase posterior).
  - *Pros:* alcance limpio y realista; el tenant queda aislado en datos de inmediato; no arrastra la complejidad de credenciales de Meta.
  - *Contras:* el tenant nuevo no puede operar WhatsApp "de inmediato" — necesita un paso adicional de conexión de número (que además cuelga del WABA global actual).
- **Opción B — El alta incluye registrar un `phone_number_id` en `whatsapp_accounts`** (dentro del mismo WABA global; el número ya debe existir en la app de Meta del proceso).
  - *Pros:* el tenant queda operativo en WhatsApp al terminar el alta, si el número ya está en el WABA global.
  - *Contras:* asume que todos los tenants comparten el mismo WABA/token (modelo "una empresa, varios números" — coherente con caso multi-sede, NO con SaaS de terceros con su propia cuenta de Meta).
- **Opción C — WABA/credenciales propias POR tenant (Embedded Signup de Meta, tokens propios cifrados)** — trabajo grande.
  - *Pros:* verdadero SaaS multi-cliente: cada negocio trae su propia cuenta de WhatsApp Business.
  - *Contras:* **fuera del alcance razonable de esta fase** — requiere front de app de Meta, Embedded Signup, almacenamiento cifrado de tokens por-tenant (C3), verificación de negocio en Meta, cambio de `graph_client` para credenciales por-tenant. Sería su propio PLAN.
- *Recomendación XAVIER (no vinculante):* **Opción A** para este slice (tenant sin canal; WhatsApp aparte). La Opción C, si el Lead la quiere, merece su propio plan futuro. **Decisión del Lead.**

### Q3 — ¿Verificación de email / aprobación manual antes de activar, o activación inmediata?
- **Opción A — Activación inmediata** (creado el tenant, el admin ya puede loguearse).
  - *Pros:* experiencia fluida; mínimo esfuerzo; encaja con alta administrativa/CLI (Q1-B/C) donde el creador ya es de confianza.
  - *Contras:* si el alta es pública (Q1-A), permite tenants basura/bots sin barrera.
- **Opción B — Verificación de email obligatoria** (el admin confirma su email antes de activar el tenant).
  - *Pros:* barrera anti-bot estándar de SaaS; imprescindible si Q1-A (autoregistro público).
  - *Contras:* introduce dependencia de envío de correo (SMTP/servicio) → decisión de infra + política SENSIBLE (¿qué servicio, on-prem o externo?); más superficie.
- **Opción C — Aprobación manual** (un humano interno revisa y activa cada alta).
  - *Pros:* control máximo; útil en fase temprana o B2B de alto valor.
  - *Contras:* no es "sin intervención manual" (contradice parcialmente el objetivo); no escala.
- *Recomendación XAVIER (no vinculante):* atada a Q1 — si Q1-A (público) → **B (verificación de email)** obligatoria; si Q1-B/C (interno) → **A (inmediata)** basta. **Decisión del Lead.**

### Q4 — ¿Hay concepto de PLANES/LÍMITES (nº de agentes, nº de conversaciones), o es binario (el tenant existe / no existe, sin límites)?
- **Opción A — Binario, sin límites** (un tenant existe o no; sin cuotas). Billing/planes **explícitamente FUERA** de esta fase.
  - *Pros:* alcance mínimo; entrega el flujo de alta sin arrastrar facturación; se puede añadir después.
  - *Contras:* no hay control de consumo por tenant (aceptable si multi-sede interno o piloto).
- **Opción B — Planes/límites básicos** (p. ej. máx. usuarios/conversaciones por tenant), SIN billing todavía.
  - *Pros:* prepara el terreno para monetizar; permite tiers.
  - *Contras:* añade modelo de datos de plan + enforcement de cuotas → más alcance; probablemente prematuro si aún no hay clientes externos.
- *Nota XAVIER:* **billing/facturación real está OUT por defecto** (§8) salvo que el Lead lo pida aquí explícitamente. Esta pregunta solo decide si hay *concepto* de límites, no cobros.
- *Recomendación XAVIER (no vinculante):* **Opción A (binario, sin límites)** para el primer slice. **Decisión del Lead.**

---

## 7.1 Respuestas del Lead (2026-09-29) — VINCULANTES

- **Q1 → Caso de uso: (i) un solo grupo de clínicas multi-sede** (confirmado, no SaaS de terceros) **→ Opción B (alta administrativa interna).** No hay autoregistro público; un admin de plataforma (interno) da de alta cada sede/tenant nuevo. Introduce el concepto de "admin de plataforma" que hoy no existe.
- **Q2 → Opción A:** el tenant se crea **SIN canal**. WhatsApp (registrar `phone_number_id` en `whatsapp_accounts`) se conecta en un paso/fase posterior, separado de esta.
- **Q3 → Opción A: activación inmediata.** Coherente con Q1-B (quien crea el tenant ya es de confianza interna) — sin verificación de email ni aprobación adicional.
- **Q4 → Opción A: binario, sin límites.** Sin planes/cuotas ni billing en este slice (billing sigue OUT por defecto, §8).

Estas 4 decisiones son vinculantes para PLAN-009 — DOCTOR STRANGE las incorpora directamente, sin volver a preguntarlas. Queda para DOCTOR STRANGE precisar el mecanismo exacto de "admin de plataforma" (¿un rol especial en `users` de un tenant existente con privilegio elevado, o un concepto separado fuera del modelo tenant-scoped?) como parte del PLAN, ya que XAVIER no lo resolvió por ser una decisión de diseño, no de alcance.

---

## 8. Fuera de alcance por defecto (OUT — salvo que el Lead lo pida en §7)

- **Billing / facturación / cobros** (pasarelas de pago, suscripciones con cargo). Fuera salvo petición explícita.
- **Planes de suscripción con límites/cuotas** — depende de §7 Q4; OUT por defecto (Opción A binaria).
- **WABA/credenciales de WhatsApp propias por tenant** (Embedded Signup de Meta, tokens propios cifrados) — §7 Q2 Opción C; su propio PLAN futuro, OUT de esta fase por defecto.
- **White-labeling / personalización visual por tenant** (logos, temas, dominios propios).
- **Migración de los tenants existentes** creados por seed/SQL — siguen como están; esta fase es solo el alta NUEVA hacia adelante.
- **Gestión avanzada de usuarios dentro del tenant** (invitar/eliminar más usuarios, roles finos más allá del primer admin) — esta fase crea SOLO el primer usuario admin; la gestión posterior de equipo es otra fase.
- **Baja/eliminación de tenants (offboarding)** y exportación de datos — fuera; esta fase es el ALTA, no la baja.
- **SSO / login federado** (Google/OIDC) — el alta usa el login existente por password (SPEC-013).

---

## 9. Trazabilidad

- Estado actual del alta (manual): `backend/app/db/seed.py`, `backend/loadtest/seed_loadtest_user.py`.
- Lectura de tenant existente: `backend/app/api/tenants.py` (`GET /tenants/me`, sin creación).
- Modelos: `backend/app/models/tenant.py`, `backend/app/models/user.py`, `backend/app/models/whatsapp_account.py`.
- Auth reutilizable: `backend/app/api/auth.py`, `backend/app/services/auth_service.py` (SPEC-013).
- Aislamiento (a consumir, no rediseñar): `backend/app/db/rls.py` (`TENANT_SCOPED_TABLES`), **ADR-004** (RLS pool-model), **ADR-008** (roles BD + RLS efectiva).
- Config de canal (evidencia de token global vs routing por-tenant): `backend/app/core/config.py:149-217`, **ADR-006** (transporte WhatsApp), **ADR-007** (routing `phone_number_id->tenant_id`).
- Contadores REALES (`.swarm/specs.json`): próximo plan libre **PLAN-009** (⚠️ `next_plan:8` desactualizado — PLAN-008 ya existe/APROBADO), `next_spec: 73`, `next_adr: 15` (próximo ADR candidato **ADR-015**).
- Siguiente paso: 🔮 DOCTOR STRANGE → **PLAN-009** (con las respuestas del Lead a §7) → aprobación del Lead → SPECs (desde `next_spec: 73`).
