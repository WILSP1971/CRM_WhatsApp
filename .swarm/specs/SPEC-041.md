# SPEC-041 — Retención/anonimización de audio + seguridad (extiende SPEC-021) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: BLACK WIDOW · Colaboran: BLACK PANTHER, CAPTAIN AMERICA, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: SEGURIDAD/DATOS · Fase: F6
- Deriva de: PLAN-004 (F6, §2.7, R-43/R-44) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Extender la política de datos personales del Entregable #2 (SPEC-021, HABEAS DATA/GDPR-like) al **audio de llamadas (dato personal / posible PHI)**: **política de retención configurable** (por defecto **audio 30 días**) con **purga/anonimización** del audio y/o transcripción, **cifrado en reposo verificado**, y **registro de acceso auditado** a audio/transcripción; con barrido de seguridad BLACK WIDOW.

## Contexto

El Entregable #2 fijó TLS, secretos (C3), borrado lógico (C2) y HABEAS DATA/GDPR-like (SPEC-021). La Fase 4 introduce el audio como novedad estructural sensible que exige retención, cifrado y acceso auditado propios. Por SUP-45, el dominio por defecto es **comercial/HABEAS DATA (Ley 1581) + GDPR-like**; por SUP-49, la retención por defecto del audio es **30 días** y luego anonimización/purga, con la transcripción retenida según SPEC-021. Si el Lead confirma **salud/PHI**, se endurece (cifrado de campo, retención estricta, acceso reforzado) según ADR-009 endurecido; esta SPEC deja los puntos de extensión listos.

## Alcance

### IN
- Política de retención **configurable** por env: días de retención de audio (por defecto 30) y de transcripción; acción al vencer (purga total o anonimización).
- Job/tarea de **purga/anonimización** del audio y/o transcripción al vencer la retención; borrado lógico previo (C2) y purga física del blob de audio del almacén cifrado.
- **Cifrado en reposo verificado** del almacén de audio (SPEC-035) y, si PHI (ADR-009 endurecido), cifrado de campo de la transcripción.
- **Registro de acceso auditado** (quién/cuándo/qué) a audio y transcripción (HABEAS DATA/PHI), consumido por la ficha (SPEC-040).
- Barrido BLACK WIDOW: sin secretos/PHI en repo/logs; permisos mínimos del almacén.

### OUT
- Implementación del almacén cifrado y allowlist (SPEC-035, reutilizada); ficha SPA (SPEC-040, consumidora del registro).
- Pruebas automatizadas de la política (SPEC-042).

## Dependencias
- Depende de SPEC-035 (almacén cifrado), SPEC-036 (`call`/`call_transcript`) y extiende SPEC-021 (HABEAS DATA/GDPR-like). Se ancla en ADR-009.

## Requisitos funcionales
- RF-01 La retención de audio y de transcripción es configurable por env, con valores por defecto (audio 30 días).
- RF-02 Al vencer la retención, el audio y/o la transcripción se purgan o anonimizan según configuración.
- RF-03 Cada acceso a audio/transcripción queda registrado (quién, cuándo, qué).

## Requisitos no funcionales
- RNF-43 Audio cifrado en reposo verificado; permisos mínimos; sin exposición pública.
- RNF-44 Cumplimiento HABEAS DATA/GDPR-like; si PHI, cifrado de campo + retención estricta + acceso reforzado (ADR-009 endurecido).
- RNF-41 La purga/anonimización ocurre on-prem; el audio nunca sale a un tercero en ningún punto del ciclo de vida.

## Criterios de aceptación (verificables)
- [ ] La política de retención (audio/transcripción) es configurable por env con defaults documentados (audio 30 días).
- [ ] Un audio que supera la retención se **purga/anonimiza** según la configuración (test de purga por política).
- [ ] El audio está **cifrado en reposo** (inspección); no accesible desde fuera del host.
- [ ] Cada acceso a audio/transcripción genera un **registro de auditoría** (HABEAS DATA/PHI).
- [ ] Barrido BLACK WIDOW: cero secretos/PHI en repo/logs; permisos mínimos del almacén.
- [ ] (Si PHI) cifrado de campo de la transcripción y acceso reforzado activables por config (ADR-009 endurecido).

## Notas de seguridad (C2/C3)
- C2: borrado lógico previo a la purga física; sin DELETE físico fuera del job de retención.
- C3: clave de cifrado y config de retención SOLO en env; nunca en repo/logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el audio (dato personal / posible PHI) se **cifra en reposo**, se **retiene según política** y su acceso queda **auditado**; **jamás sale a un tercero** en ningún punto del ciclo de vida (ADR-009). Un cambio a retención más laxa o a PHI es cambio sensible → aprobación del Lead + notificación Telegram (C6).

## Riesgos
- R-43 (cifrado/almacenamiento): cifrado en reposo verificado; permisos mínimos; barrido BLACK WIDOW.
- R-44 (retención/PHI): política configurable + purga/anonimización + acceso auditado; endurecimiento PHI (ADR-009).
- R-41 (audio a terceros): la purga/anonimización es on-prem; sin egress.

## Checkpoints aplicables
- C2 (borrado lógico antes de purga). C3 (secretos en env). C4 (criterios verificables). C6 (cambio de retención/PHI sensible). C8 (origen PLAN-004).
