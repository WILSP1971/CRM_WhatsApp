# SPEC-013 — Autenticación, gestión de sesión y multi-tenant

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK WIDOW, BLACK PANTHER, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: BACKEND/SEGURIDAD · Fase: F2
- Deriva de: PLAN-002 (F2) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Implementar login/JWT con hashing fuerte (Argon2/bcrypt), usuarios y roles por tenant, y un middleware que **inyecta `tenant_id` en la sesión de BD** para forzar RLS en cada request autenticado.

## Contexto

Fase F2 (SENSIBLE — requiere aprobación explícita del Lead por tocar auth). Prerequisito de SPEC-014..SPEC-019: todo endpoint opera bajo un tenant autenticado. El middleware traduce el JWT al `SET app.tenant_id` de la sesión que activa RLS (SPEC-012). Secretos (JWT secret, credenciales) SOLO en env (C3).

## Alcance

### IN
- Registro/login de usuarios; contraseñas hasheadas con Argon2 (o bcrypt); nunca en claro.
- Emisión/validación de JWT (o sesión segura) con expiración y refresh controlado.
- Roles por tenant (p.ej. admin/agente) y scoping de permisos.
- Middleware que valida JWT e inyecta `tenant_id` en la sesión de BD (activa RLS `FORCE`).
- Endpoints `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Bloqueo por intentos fallidos / rate-limit básico de login (Redis).

### OUT
- Endpoints de dominio de negocio (SPEC-014).
- SSO/OAuth externo, MFA avanzada (Fase 3+).
- TLS/terminación HTTPS a nivel de despliegue (SPEC-021/023).

## Dependencias
- Depende de SPEC-011 (infra) y SPEC-012 (users/roles + RLS). Prerequisito de SPEC-014..SPEC-019.

## Requisitos funcionales
- RF-01 Un usuario autenticado solo ve datos de **su** tenant (verificable con RLS).
- RF Login válido devuelve token; login inválido devuelve 401 sin filtrar información.
- RF Cada request autenticado fija `app.tenant_id` en la sesión antes de tocar datos.
- RF Roles por tenant restringen acciones sensibles.

## Requisitos no funcionales
- RNF-01 Contraseñas hasheadas (Argon2/bcrypt), nunca en claro ni logueadas.
- RNF-02 Aislamiento multi-tenant reforzado por el middleware→RLS.
- Secretos (JWT secret) SOLO en env (C3).

## Criterios de aceptación (verificables)
- [ ] Contraseñas almacenadas como hash Argon2/bcrypt (no reversibles, con salt).
- [ ] `POST /auth/login` con credenciales válidas emite JWT; inválidas → 401.
- [ ] Un request con token del tenant A no puede leer datos del tenant B (RLS lo impide).
- [ ] El middleware fija `app.tenant_id` en la sesión en cada request autenticado.
- [ ] JWT secret y credenciales provienen de env; escaneo BLACK WIDOW sin secretos en repo.
- [ ] Endpoints protegidos devuelven 401 sin token válido.
- [ ] Rate-limit de login activo (bloqueo tras N intentos).

## Notas de seguridad (C2/C3)
- C3: JWT secret, credenciales BD/Redis SOLO en env; barrido BLACK WIDOW.
- C2: baja lógica de usuarios (Activo/Inactivo), no DELETE físico.

## Restricción SENSIBLE aplicable
- Sin auth externa/IdP de terceros en el slice #1; procesamiento de credenciales 100% on-prem.

## Riesgos
- R-23 (fuga cross-tenant): middleware→RLS + test cross-tenant (SPEC-022).
- R-26 (secretos en texto plano): env only + escaneo.

## Checkpoints aplicables
- C2 (borrado lógico usuarios). C3 (sin secretos). C4 (criterios verificables). C6 (cambio sensible: auth → aprobación Lead). C8 (origen PLAN-002).

## Nota de aprobación
- **SPEC SENSIBLE (auth):** requiere aprobación explícita del Lead y notificación (`.claude/hooks/notify.sh`).
