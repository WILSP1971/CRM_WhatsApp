# SPEC-021 — Seguridad y datos personales: TLS, secretos (C3), borrado lógico (C2), HABEAS DATA/GDPR-like

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK WIDOW, BLACK PANTHER, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: SEGURIDAD/DATOS · Fase: F7
- Deriva de: PLAN-002 (F7) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Cerrar la capa transversal de seguridad y protección de datos personales: **TLS** en tránsito, **cifrado en reposo** de datos personales, **secretos SOLO en env** (C3), **borrado lógico** (C2), **minimización/retención** configurable y **registro de acceso**, cumpliendo HABEAS DATA (Ley 1581 Colombia) y buenas prácticas GDPR-like.

## Contexto

Fase F7 (SENSIBLE — requiere aprobación explícita del Lead por tocar datos personales y seguridad). Transversal: se diseña desde F1/F2 (RLS, secretos, borrado lógico) y se **consolida/audita** aquí sobre el conjunto. Los datos son de contacto/comercial (no PHI/HIPAA). Base de CE-25 y del barrido BLACK WIDOW (secretos, cross-tenant, egress).

## Alcance

### IN
- TLS en tránsito (terminación HTTPS/WSS) para API, WebChat y SPA.
- Cifrado en reposo de datos personales (a nivel de volumen/campo según sensibilidad).
- Secretos (JWT, credenciales BD/Redis) SOLO en env/secret manager; `.env` fuera del repo (C3).
- Borrado lógico Activo/Inactivo en entidades transaccionales (C2) verificado transversalmente.
- Minimización de datos y **retención configurable** (purga según política).
- Registro de acceso a datos personales (quién/qué/cuándo) para auditoría (HABEAS DATA).
- Barrido BLACK WIDOW: secretos en repo, fugas cross-tenant, egress IA.

### OUT
- Auth/JWT en sí (SPEC-013) — aquí se audita, no se implementa de nuevo.
- Derecho al olvido físico / auditoría formal externa (RNF adicionales si el Lead lo pide).
- SSO/MFA avanzada (Fase 3+).

## Dependencias
- Depende de SPEC-013 (auth/secretos), SPEC-012 (RLS/borrado lógico) y SPEC-011 (env/infra). Transversal a F1–F6; se consolida al final.

## Requisitos funcionales
- RF Datos personales cifrados en reposo y transmitidos por TLS/WSS.
- RF Retención configurable: los datos vencidos se purgan/anonimizan según política.
- RF Todo acceso a datos personales queda registrado (auditoría HABEAS DATA).
- RF Borrado lógico (no DELETE físico) en entidades transaccionales.

## Requisitos no funcionales
- RNF-01 Secretos SOLO en env (C3); nunca en repo/logs.
- RNF-02 Aislamiento cross-tenant reforzado (RLS) verificado.
- RNF Cumplimiento HABEAS DATA (Ley 1581) + buenas prácticas GDPR-like.

## Criterios de aceptación (verificables)
- [ ] API/WebChat/SPA sirven por TLS/WSS; tráfico en claro rechazado o redirigido.
- [ ] Datos personales cifrados en reposo (verificable en volumen/campo).
- [ ] Escaneo BLACK WIDOW: **cero** secretos en el repo; `.env.example` sin valores reales.
- [ ] Entidades transaccionales usan borrado lógico (Activo/Inactivo), sin DELETE físico.
- [ ] Retención configurable aplicada: datos vencidos purgados/anonimizados según política.
- [ ] Registro de acceso a datos personales presente y consultable (auditoría).
- [ ] Test cross-tenant confirma que RLS impide fugas entre tenants (coordinado con SPEC-022).

## Notas de seguridad (C2/C3)
- C2: borrado lógico transversal verificado.
- C3: secretos SOLO en env; barrido BLACK WIDOW sin hallazgos.

## Restricción SENSIBLE aplicable
- Procesamiento de datos personales 100% on-prem; ningún tercero recibe datos personales ni inferencia. HABEAS DATA/GDPR-like.

## Riesgos
- R-26 (secretos en texto plano): env only + escaneo BLACK WIDOW.
- R-23 (fuga cross-tenant): RLS + test cross-tenant.
- R-22 (fuga de egress IA): egress bloqueado + auditoría (SPEC-016/022).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C6 (cambio sensible: datos personales/seguridad → aprobación Lead). C8 (origen PLAN-002).

## Nota de aprobación
- **SPEC SENSIBLE (seguridad/datos personales):** requiere aprobación explícita del Lead y notificación (`.claude/hooks/notify.sh`).
