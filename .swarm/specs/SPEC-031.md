# SPEC-031 — Integración SPA del canal WhatsApp por feature-flag (reutiliza SPEC-020)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: FRONTEND · Fase: F6
- Deriva de: PLAN-003 (F6) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Mostrar el canal `whatsapp` en la Bandeja omnicanal real de la SPA (junto a WebChat), con indicador de ventana 24 h/plantilla, tras el feature-flag `VITE_USE_REAL_API`; con el flag **OFF la maqueta del Entregable #1 permanece intacta**.

## Contexto

La Bandeja ya soporta multi-canal (Entregable #1) y la SPA ya consume APIs reales por feature-flag (SPEC-020). `conversations.canal` es string; `whatsapp` entra con el mismo contrato que WebChat. Esta SPEC añade la visualización del canal real sin romper contratos ni la maqueta.

## Alcance

### IN
- La Bandeja muestra conversaciones `canal="whatsapp"` junto a WebChat con el mismo contrato (`conversations`, `messages`, `rag.citations`).
- Indicador de estado de la ventana de 24 h / necesidad de plantilla en la conversación de WhatsApp.
- Respeto estricto de los contratos de tipo (`src/lib/types.ts`); flag `VITE_USE_REAL_API` OFF = maqueta intacta.

### OUT
- Backend del canal (SPEC-026..030); lógica de envío/aprobación (SPEC-029/SPEC-019, reutilizada).

## Dependencias
- Depende de SPEC-027 (conversaciones WhatsApp reales) y SPEC-029/SPEC-030 (estados) y reutiliza SPEC-020 (feature-flag). 

## Requisitos funcionales
- RF-01 Con el flag ON, la Bandeja muestra conversaciones WhatsApp junto a WebChat.
- RF-02 Se muestra el indicador de ventana 24 h / plantilla en la conversación WhatsApp.
- RF-03 Con el flag OFF, la maqueta del Entregable #1 queda intacta (sin regresión).

## Requisitos no funcionales
- RNF-07 Sin romper el Entregable #1; feature-flag reversible.
- RNF-04 La SPA solo muestra datos del tenant autenticado.

## Criterios de aceptación (verificables)
- [ ] Con `VITE_USE_REAL_API=ON`, aparece al menos una conversación `whatsapp` en la Bandeja real.
- [ ] La conversación WhatsApp respeta el contrato de tipos (sin errores de `types.ts`).
- [ ] Se visualiza el indicador de ventana 24 h/plantilla (dentro/fuera de ventana).
- [ ] Con `VITE_USE_REAL_API=OFF`, la maqueta del Entregable #1 se ve idéntica (sin regresión visual/funcional).
- [ ] Suites del Entregable #1 verdes tras el cambio.

## Notas de seguridad (C2/C3)
- C2: la SPA no muestra conversaciones inactivas (borrado lógico respetado).
- C3: sin secretos en el frontend; tokens de WhatsApp solo en backend.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): la SPA consume solo la API on-prem; no habla con Meta ni con IA externa. El transporte a Meta ocurre en el backend (SPEC-029).

## Riesgos
- R-39 (regresión #1): feature-flag reversible; dominio agnóstico de canal; suites verdes.

## Checkpoints aplicables
- C2 (borrado lógico visible). C3 (sin secretos en front). C4 (criterios verificables). C8 (origen PLAN-003).
