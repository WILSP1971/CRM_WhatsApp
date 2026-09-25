# SPEC-040 — Integración SPA: ficha de llamada por feature-flag (VoiceBot SPEC-006 de mock a datos reales)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: FRONTEND · Fase: F5
- Deriva de: PLAN-004 (F5) · Clasificación: SENSIBLE (`.no-externo`)
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Convertir el módulo VoiceBot visual de la maqueta (SPEC-006) de **mock a datos reales** tras el feature-flag `VITE_USE_REAL_API`, mostrando una **ficha de llamada** con transcripción real (segmentos + timestamps), sentimiento, resumen, borrador citado y reproductor de audio (según política de retención); con el flag **OFF la maqueta de los Entregables #1/#2/#3 permanece intacta**.

## Contexto

La SPA ya consume APIs reales por feature-flag (SPEC-020) y el Entregable #3 aplicó ese mismo patrón al canal WhatsApp (SPEC-031). El módulo VoiceBot (SPEC-006) existe como representación visual desde el Entregable #1. Esta SPEC lo enchufa a los datos reales de voz (SPEC-036/038/039) respetando los contratos de tipo (`src/lib/types.ts`) y sin romper lo existente. El reproductor de audio solo se ofrece si la retención (SPEC-041) conserva el audio; si fue purgado/anonimizado, se muestra solo la transcripción.

## Alcance

### IN
- La ficha de llamada muestra transcripción real (segmentos + timestamps + hablante), sentimiento, resumen y borrador citado (`rag.citations`).
- Reproductor de audio **según política de retención** (si el audio existe); acceso a audio/transcripción sujeto al registro de auditoría (SPEC-041).
- Respeto estricto de los contratos de tipo (`src/lib/types.ts`); flag `VITE_USE_REAL_API` OFF = maqueta intacta.
- Reutiliza SPEC-020 (feature-flag) y el layout del módulo VoiceBot (SPEC-006).

### OUT
- Backend de voz (SPEC-036..039); política/registro de retención (SPEC-041, consumida).
- Envío autónomo por voz o auto-respuesta (fuera de alcance; el human-in-the-loop, SPEC-019, se reutiliza).

## Dependencias
- Depende de SPEC-038 (transcripción real) y SPEC-039 (enriquecimiento) y reutiliza SPEC-020 (feature-flag) y SPEC-006 (módulo VoiceBot). Consume SPEC-041 (retención) para el reproductor.

## Requisitos funcionales
- RF-01 Con el flag ON, la ficha de llamada muestra transcripción real, sentimiento, resumen y borrador citado.
- RF-02 El reproductor de audio aparece solo si la retención conserva el audio; si fue purgado, se muestra solo la transcripción.
- RF-03 Con el flag OFF, la maqueta de los Entregables #1/#2/#3 queda intacta (sin regresión).

## Requisitos no funcionales
- RNF-07 Sin romper #1/#2/#3; feature-flag reversible.
- RNF-47 La SPA solo muestra datos de voz del tenant autenticado.
- RNF-44 El acceso a audio/transcripción desde la ficha queda registrado (HABEAS DATA, SPEC-041).

## Criterios de aceptación (verificables)
- [ ] Con `VITE_USE_REAL_API=ON`, aparece al menos una ficha de llamada con transcripción real (segmentos + timestamps).
- [ ] La ficha muestra sentimiento, resumen y borrador con **≥3 citas** trazables.
- [ ] El reproductor de audio aparece solo si el audio no ha sido purgado/anonimizado; si lo fue, se muestra la transcripción sin reproductor.
- [ ] La ficha respeta el contrato de tipos (sin errores de `types.ts`).
- [ ] Con `VITE_USE_REAL_API=OFF`, la maqueta de #1/#2/#3 se ve idéntica (sin regresión visual/funcional).
- [ ] Suites de #1/#2/#3 verdes tras el cambio.

## Notas de seguridad (C2/C3)
- C2: la SPA no muestra llamadas/transcripciones inactivas (borrado lógico respetado).
- C3: sin secretos en el frontend; el audio se sirve por la API on-prem, nunca desde un tercero.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): la SPA consume solo la API on-prem; no habla con el PBX, con STT/TTS de terceros ni con IA externa. El audio (posible PHI) se sirve on-prem y su acceso queda auditado (SPEC-041).

## Riesgos
- R-49 (regresión #1/#2/#3): feature-flag reversible; dominio agnóstico de canal; suites verdes.
- R-44 (PHI/acceso al audio): reproductor sujeto a retención + acceso auditado (SPEC-041).

## Checkpoints aplicables
- C2 (borrado lógico visible). C3 (sin secretos en front). C4 (criterios verificables). C8 (origen PLAN-004).
