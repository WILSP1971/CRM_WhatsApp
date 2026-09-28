# SPEC-070 — SPA/UX: acción opt-in "responder con audio" + botón "escuchar antes de enviar" + reproductor + estados AAA + feature-flag (flag OFF = texto intacto) + disclaimer de voz sintética (marca ligera) 🔴 SENSIBLE

- Estado: APROBADA · Responsable: SPIDER-MAN · Colaboran: DAREDEVIL, CAPTAIN AMERICA, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: FRONTEND/UX · Fase: F3
- Deriva de: PLAN-008 (F3, §2.IN.7, §3.1/§3.4, §4, §6 R-85, CE-81/CE-85/CE-87) · Clasificación: SENSIBLE (`.no-externo`) · ADR-014/ADR-012
- APROBADO SPEC-070 por el Lead (bloque PLAN-008) — 2026-09-28.

## Objetivo

Añadir a la SPA la **experiencia opt-in** para responder una nota de voz con audio, sobre el flujo human-in-the-loop existente: una acción explícita **"responder con audio"** (Q2-A, por defecto la respuesta sigue siendo texto), un botón **"escuchar antes de enviar"** con **reproductor** del clip generado bajo demanda, y **estados accesibles (WCAG AAA)** de carga/generando/listo/error. Todo detrás de un **feature-flag** (patrón SPEC-020/031): con el flag **OFF**, el flujo de respuesta en **texto queda intacto**. La **marca/disclaimer de voz sintética ligera** (p. ej. "🔊 respuesta de voz asistida") es un **requisito firme** (decisión vinculante del Lead, ADR-014/SPEC-068), no opcional.

## Contexto

El flujo de aprobación actual (SPEC-019/029, SPA SPEC-020/031) muestra el borrador de texto (`rag_draft`) y el agente lo aprueba/edita/descarta antes de enviar por Graph API. Esta SPEC lo **extiende** consumiendo el estado y el clip que expone el servicio TTS de SPEC-069 (`respuesta_modo`, `tts_estado` = `no_solicitado`/`generando`/`listo`/`error`, y el clip bajo demanda). El patrón de feature-flag de reemplazo progresivo de mocks/canales ya está establecido (SPEC-020: `VITE_USE_REAL_API`; SPEC-031: canal WhatsApp por flag); esta SPEC sigue el mismo patrón para que **flag OFF = comportamiento actual (solo texto) idéntico**. La accesibilidad AAA es requisito del proyecto (ADR-002, SPEC-009): los estados y el reproductor deben ser operables por teclado y anunciados a lectores de pantalla.

## Alcance

### IN
- **Acción explícita "responder con audio" (opt-in, Q2-A):** control en la UI de respuesta que marca `respuesta_modo="audio"`; por defecto la respuesta es **texto** (el control no altera el flujo de texto si no se activa).
- **Botón "escuchar antes de enviar" (Q1-C):** dispara la generación del clip **bajo demanda** (SPEC-069) y muestra un **reproductor** para que el agente escuche antes de aprobar el audio concreto. La aprobación del audio es explícita.
- **Estados accesibles (AAA):** carga/generando/listo/error del clip, con contraste ≥7:1, foco gestionado, operables por teclado y anunciados vía `aria-live`/roles adecuados; el reproductor tiene controles accesibles (play/pausa, tiempo, etiqueta).
- **Disclaimer/marca de voz sintética ligera (firme):** al enviar una respuesta de audio se acompaña de una marca ligera (p. ej. prefijo/etiqueta "🔊 respuesta de voz asistida") según ADR-014/SPEC-068; presente y verificable, configurable en su texto pero **no desactivable** por defecto (decisión del Lead, CE-87).
- **Feature-flag (patrón SPEC-020/031):** toda la UX de audio queda tras un flag; **flag OFF → la UI de respuesta es la actual (solo texto), sin ningún control de audio visible** ni cambio de comportamiento.
- **Integración con el estado de SPEC-069:** la SPA refleja `tts_estado` y habilita/inhabilita "enviar audio" según el estado (no permite enviar sin clip listo en la ruta de escucha, ni sin guion aprobado en la ruta por defecto).
- **Manejo de error en UI:** `tts_estado="error"` se muestra de forma accesible con opción de reintentar o **caer a texto** (el guion sigue disponible), sin dejar al agente bloqueado.

### OUT
- Servicio/worker TTS, cola y subida por WhatsApp (SPEC-069) — la SPA solo consume su estado/clip.
- ADR-014/modelo de datos/config (SPEC-068) y decisión de motor (SPEC-067).
- Pruebas e2e/seguridad/no-regresión (SPEC-071) y docs/deploy (SPEC-072).
- Reproducir/gestionar la **nota de voz entrante** del cliente (eso es #5, SPEC-059) — aquí solo el audio de **salida**.
- Persistencia del clip (no se persiste por defecto, ADR-014).

## Dependencias
- Depende de **SPEC-069** (estado `tts_estado`/clip bajo demanda + envío) y **SPEC-068/ADR-014** (opt-in, disclaimer decidido). Reutiliza SPEC-020/031 (feature-flag, integración SPA por flag) y SPEC-019/029 (flujo de aprobación en la SPA), y el design system AAA (SPEC-002/009, ADR-002). **Prerequisito de SPEC-071/072.**

## Requisitos funcionales
- RF-01 La UI de respuesta ofrece una acción explícita "responder con audio" (opt-in); por defecto la respuesta es texto.
- RF-02 El botón "escuchar antes de enviar" genera el clip bajo demanda y lo reproduce; el envío del audio requiere aprobación explícita del clip.
- RF-03 La UI refleja `tts_estado` (no_solicitado/generando/listo/error) con estados accesibles AAA y habilita el envío solo cuando corresponde.
- RF-04 Toda respuesta de audio incluye la marca/disclaimer de voz sintética ligero (firme, no desactivable por defecto).
- RF-05 Con el feature-flag OFF, la UI de respuesta es la actual (solo texto), sin controles de audio ni cambio de comportamiento.
- RF-06 En `tts_estado="error"`, la UI ofrece reintentar o caer a texto sin bloquear al agente.

## Requisitos no funcionales
- RNF-A11Y **Accesibilidad AAA:** contraste ≥7:1, operables por teclado, foco visible/gestionado, estados anunciados (`aria-live`), reproductor con controles etiquetados (ADR-002, SPEC-009).
- RNF-FLAG El flag OFF garantiza cero cambio en el flujo de texto (patrón SPEC-020/031); ninguna dependencia de audio se carga/ejecuta con flag OFF.
- RNF-01 Sin egress nuevo desde la SPA hacia terceros de voz; el clip se obtiene del backend propio; la subida a WhatsApp la hace el backend (SPEC-069), no la SPA.
- RNF-HITL La UI **no** permite enviar audio sin la aprobación humana correspondiente (guion aprobado o clip escuchado y aprobado).

## Criterios de aceptación (verificables)
- [ ] Con el flag ON, la UI de respuesta muestra "responder con audio" (opt-in); por defecto la respuesta es texto.
- [ ] "Escuchar antes de enviar" genera y reproduce el clip bajo demanda; el envío del audio requiere aprobación explícita del clip.
- [ ] Los estados carga/generando/listo/error son accesibles (contraste ≥7:1, teclado, `aria-live`); auditoría de accesibilidad AAA pasa (SPEC-071).
- [ ] Toda respuesta de audio muestra la marca/disclaimer de voz sintética ligero; verificable en la UI y en lo que se envía.
- [ ] Con el flag OFF, no aparece ningún control de audio y el flujo de texto es idéntico al actual (test de no-regresión).
- [ ] La UI no habilita el envío de audio sin guion aprobado (ruta por defecto) ni sin clip aprobado (ruta escucha).
- [ ] `tts_estado="error"` se muestra accesible con reintentar/caer a texto; el agente no queda bloqueado.

## Notas de seguridad (C2/C3)
- C2: la SPA no borra físicamente nada; opera sobre el estado del backend (borrado lógico gestionado en backend).
- C3: sin secretos en el frontend; el token de Graph API vive solo en backend; el clip se sirve por el backend propio, no por un tercero.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE (sin egress nuevo): la SPA consume el clip/estado del backend propio; **no** llama a ningún TTS de terceros; la única salida a `graph.facebook.com` la realiza el backend (SPEC-069, ADR-006). El disclaimer de voz sintética mitiga el riesgo legal/reputacional (R-85, Ley 1581).

## Riesgos
- R-85 (voz sintética/legal): disclaimer/marca ligera **firme** implementado y verificado (CE-87); decisión del Lead ya tomada (ADR-014).
- R-82 (regresión del flujo de texto): feature-flag con OFF = texto intacto (patrón SPEC-020/031); test de no-regresión.
- R-A11Y (accesibilidad de estados/reproductor): diseño AAA + auditoría (SPEC-071), controles etiquetados y operables por teclado.

## Checkpoints aplicables
- C2 (borrado lógico, gestionado en backend). C3 (sin secretos en frontend). C4 (criterios verificables). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
