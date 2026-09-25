# SPEC-058 — Retención/cifrado extendido al `audio_ref` de mensajería (extiende SPEC-041, un solo régimen) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: BLACK WIDOW · Colaboran: BLACK PANTHER, CAPTAIN AMERICA, HAWKEYE, WOLVERINE · Prioridad: ALTA · Tipo: SEGURIDAD/DATOS · Fase: F5
- Deriva de: PLAN-006 (F5, §3.6, R-63/R-64) · Clasificación: SENSIBLE (`.no-externo`) · ADR-009/ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

**Ampliar el selector** de la política de retención/cifrado ya existente (SPEC-041, HABEAS DATA/GDPR-like, audio de llamadas 30 días) para que cubra **también el `audio_ref` de mensajería** (nota de voz de WhatsApp, `messages.audio_ref` de SPEC-053): mismo `audio_store.py` cifrado (SPEC-035), **mismo job de purga/anonimización**, mismo cifrado en reposo verificado y mismo acceso auditado. **Un solo régimen de retención**, sin política paralela que pueda desincronizarse. Plazo por defecto **30 días** (P4 confirmado: mismo plazo que SPEC-041), configurable por env.

## Contexto

SPEC-041 fijó una política **configurable** de retención de audio (por defecto 30 días → purga/anonimización) sobre el `audio_ref` de `call`, con cifrado en reposo (SPEC-035) y registro de acceso auditado, extendiendo SPEC-021. La nota de voz de WhatsApp introduce **otro origen** de `audio_ref` (`messages.audio_ref`), pero **no** justifica un régimen nuevo: es el mismo dato personal (posible PHI), el mismo almacén cifrado y el mismo ciclo de vida. Por P4 (confirmado por el Lead), el plazo por defecto es **el mismo que SPEC-041 (30 días)**; ajustable por env si el negocio pide un plazo distinto para mensajería. La transcripción escrita en `messages.contenido` se retiene como cualquier `Message` (SPEC-021), con borrado lógico (C2).

## Alcance

### IN
- **Ampliación del selector** del job de purga/anonimización de SPEC-041 para incluir `messages.audio_ref` (origen mensajería) además de `calls.audio_ref` (origen voz). **Mismo job, mismo código**, un selector más amplio — no un job nuevo.
- Purga/anonimización del `audio_ref` de mensajería al vencer la retención (**default 30 días**, P4, configurable por env): borrado lógico previo (C2) + purga física del blob del almacén cifrado; la transcripción (`messages.contenido`) se retiene/purga según la política del `Message` (SPEC-021).
- **Cifrado en reposo verificado** del `audio_ref` de mensajería (reutiliza `audio_store.py`, SPEC-035, sin excepción); si PHI (ADR-009 endurecido), puntos de extensión ya listos (cifrado de campo de la transcripción activable por config).
- **Registro de acceso auditado** (quién/cuándo/qué) al audio/transcripción de mensajería, mismo mecanismo que SPEC-041.
- Barrido BLACK WIDOW sobre el nuevo origen: sin secretos/PHI en repo/logs; permisos mínimos del almacén; el `audio_ref` de mensajería no queda expuesto públicamente.

### OUT
- Implementación del almacén cifrado y allowlist (SPEC-035, reutilizada); política base de SPEC-041 (extendida, no reescrita).
- Pruebas automatizadas de la política (SPEC-060).
- Reproductor/badge en la SPA (SPEC-059, consumidor del estado de retención).

## Dependencias
- Depende de SPEC-053 (`messages.audio_ref`), SPEC-035 (almacén cifrado) y **extiende SPEC-041** (política de retención) y SPEC-021 (HABEAS DATA/GDPR-like). Se ancla en ADR-009 y ADR-013.

## Requisitos funcionales
- RF-01 El job de purga/anonimización de SPEC-041 cubre **también** `messages.audio_ref` (origen mensajería), con el **mismo** código y un selector ampliado.
- RF-02 El `audio_ref` de mensajería que supera la retención (default 30 días) se **purga/anonimiza** según configuración.
- RF-03 Cada acceso al audio/transcripción de mensajería queda **registrado** (quién/cuándo/qué).
- RF-04 El plazo de retención de mensajería es **configurable por env**, con default 30 días (P4, igual a SPEC-041).

## Requisitos no funcionales
- RNF-43 `audio_ref` de mensajería **cifrado en reposo** verificado; permisos mínimos; sin exposición pública.
- RNF-64 **Un solo régimen de retención**: no se crea política paralela; el mismo job cubre voz y mensajería (sin riesgo de desincronización).
- RNF-41 La purga/anonimización ocurre on-prem; el audio de mensajería nunca sale a un tercero en ningún punto del ciclo de vida.

## Criterios de aceptación (verificables)
- [ ] El job de purga/anonimización (SPEC-041) procesa `messages.audio_ref` además de `calls.audio_ref` (un solo job, selector ampliado — inspección de código/test).
- [ ] Un `audio_ref` de mensajería que supera la retención se **purga/anonimiza** según config (test de purga por política).
- [ ] El `audio_ref` de mensajería está **cifrado en reposo** (inspección); no accesible desde fuera del host.
- [ ] Cada acceso a audio/transcripción de mensajería genera un **registro de auditoría** (HABEAS DATA/PHI).
- [ ] El plazo por defecto es **30 días** (P4), configurable por env (test con plazo reducido que dispara la purga).
- [ ] Barrido BLACK WIDOW: cero secretos/PHI en repo/logs; permisos mínimos del almacén; **una sola** política (no hay régimen paralelo).

## Notas de seguridad (C2/C3)
- C2: borrado lógico del `Message`/`audio_ref` previo a la purga física; sin DELETE físico fuera del job de retención.
- C3: clave de cifrado y config de retención SOLO en env; nunca en repo/logs.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el audio de mensajería (dato personal / posible PHI) se **cifra en reposo**, se **retiene según la misma política de SPEC-041** y su acceso queda **auditado**; **jamás sale a un tercero** en ningún punto del ciclo de vida (ADR-009). Un cambio a retención más laxa o a PHI es cambio sensible → aprobación del Lead + notificación Telegram (C6).

## Riesgos
- R-63 (cifrado/almacenamiento del audio de mensajería): cifrado en reposo verificado (SPEC-035); permisos mínimos; barrido BLACK WIDOW.
- R-64 (retención/PHI de mensajería): mismo régimen que SPEC-041 (un solo job); purga/anonimización configurable; acceso auditado; sin política paralela desincronizable.
- R-61 (audio a terceros): la purga/anonimización es on-prem; sin egress.

## Checkpoints aplicables
- C2 (borrado lógico antes de purga). C3 (secretos en env). C4 (criterios verificables). C6 (cambio de retención/PHI sensible). C8 (origen PLAN-006).
