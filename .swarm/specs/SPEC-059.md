# SPEC-059 — SPA: badge discreto "transcrito de audio" en la ficha de conversación (reproductor pospuesto, P3)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: MEDIA · Tipo: FRONTEND · Fase: F6
- Deriva de: PLAN-006 (F6, §2.11 · P3 supuesto por defecto confirmado) · Clasificación: SENSIBLE (`.no-externo`) · ADR-013
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Añadir en la SPA una **indicación visual discreta "transcrito de audio"** (badge) en los mensajes de la ficha de conversación cuyo origen es una nota de voz de WhatsApp (`tipo="audio"`, SPEC-053), para dar **trazabilidad al agente** de que el texto proviene de una transcripción y no de un mensaje escrito. Según P3 (supuesto por defecto confirmado por el Lead): **badge sí, reproductor del clip POSPUESTO** (se retoma solo si la política de retención, SPEC-058, garantiza la disponibilidad del clip). Con el feature-flag OFF, la maqueta de #1–#4 permanece intacta.

## Contexto

La SPA ya consume APIs reales por feature-flag `VITE_USE_REAL_API` (SPEC-020) y el canal WhatsApp ya se integró bajo ese patrón (SPEC-031). La bandeja ya muestra `Message.contenido`; tras la transcripción (SPEC-056) el `Message` de audio es texto normal, por lo que **sin esta SPEC la nota de voz ya aparecería como texto** — el badge es un añadido de bajo esfuerzo que mejora la trazabilidad. Requiere: (a) que el DTO/serializador del backend exponga `tipo` (`"audio"`) del `Message` (SPEC-053) en el contrato de la API que consume la SPA; (b) un badge en el componente de mensaje del frontend. El **reproductor** queda pospuesto (P3): reintroducirlo dependería de que SPEC-058 conserve el clip y de resolver el acceso auditado al audio (SPEC-058), fuera de este slice.

## Alcance

### IN
- Exposición aditiva de `Message.tipo` (`"audio"`) en el DTO/serializador de mensajes del backend que consume la SPA (sin romper el contrato de `src/lib/types.ts`; campo opcional/aditivo).
- **Badge discreto "transcrito de audio"** en el componente de mensaje de la ficha de conversación cuando `tipo=="audio"`; accesible (texto/aria, contraste conforme al design system del Entregable #1).
- Respeto del feature-flag `VITE_USE_REAL_API`: **OFF = maqueta de #1–#4 intacta** (sin regresión visual/funcional).
- Reutiliza SPEC-020 (feature-flag) y SPEC-031 (integración WhatsApp en la SPA).

### OUT
- **Reproductor del clip de audio: POSPUESTO** (P3) — no se implementa; se retomaría solo con SPEC-058 garantizando disponibilidad del clip + acceso auditado.
- Backend de descarga/STT/enriquecimiento (SPEC-054/056/057, consumidos indirectamente).
- Cualquier envío/auto-respuesta desde la SPA (el human-in-the-loop de SPEC-019 se reutiliza).

## Dependencias
- Depende de SPEC-053 (`Message.tipo="audio"`) y SPEC-056 (transcripción visible en `contenido`); reutiliza SPEC-020 (feature-flag) y SPEC-031 (SPA WhatsApp). Consumiría SPEC-058 si en el futuro se reintroduce el reproductor.

## Requisitos funcionales
- RF-01 Con el flag ON, un mensaje `tipo="audio"` muestra un **badge discreto "transcrito de audio"** junto a su contenido transcrito.
- RF-02 Un mensaje de texto normal **no** muestra el badge.
- RF-03 Con el flag OFF, la maqueta de #1–#4 queda intacta (sin regresión).

## Requisitos no funcionales
- RNF-07 Sin romper #1–#4; feature-flag reversible; respeta el contrato de tipos (`src/lib/types.ts`).
- RNF-47 La SPA solo muestra datos del tenant autenticado (sin cambio; hereda RLS de la API).
- A11y: el badge cumple el estándar de accesibilidad/contraste del Entregable #1 (SPEC-009).

## Criterios de aceptación (verificables)
- [ ] Con `VITE_USE_REAL_API=ON`, un mensaje transcrito de audio muestra el **badge "transcrito de audio"**; un mensaje de texto no lo muestra.
- [ ] El DTO de mensajes expone `tipo` de forma **aditiva** sin romper `src/lib/types.ts`.
- [ ] El badge es accesible (aria/contraste conforme SPEC-009).
- [ ] Con `VITE_USE_REAL_API=OFF`, la maqueta de #1–#4 se ve idéntica (sin regresión visual/funcional).
- [ ] **No** se implementa reproductor de audio (pospuesto, P3).
- [ ] Suites de #1–#4 verdes tras el cambio.

## Notas de seguridad (C2/C3)
- C2: la SPA no muestra mensajes inactivos (borrado lógico respetado).
- C3: sin secretos en el frontend; el audio (si algún día se reproduce) se serviría on-prem con acceso auditado (SPEC-058), nunca desde un tercero.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): la SPA consume solo la API on-prem; no habla con Meta, STT/TTS de terceros ni IA externa. El badge es puramente presentacional.

## Riesgos
- R-70 (regresión #1–#4): feature-flag reversible; cambio aditivo; suites verdes.
- (Alcance) Si el Lead prefiere mínimo esfuerzo, esta SPEC puede descartarse y la transcripción se vería como texto normal (el badge es opcional); se mantiene por P3 (badge sí) con reproductor pospuesto.

## Checkpoints aplicables
- C2 (borrado lógico visible). C3 (sin secretos en front). C4 (criterios verificables). C8 (origen PLAN-006).
