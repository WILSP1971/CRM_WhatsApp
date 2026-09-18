# SPEC-020 — Integración SPA con APIs reales por feature-flag (reemplazo progresivo de mocks)

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: FRONTEND/INTEGRACION · Fase: F6
- Deriva de: PLAN-002 (F6) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Conectar la SPA del Entregable #1 a las **APIs reales** mediante un **feature-flag** `VITE_USE_REAL_API`, reemplazando los mocks **módulo a módulo** de forma reversible, **sin romper el Entregable #1** (con el flag apagado, la maqueta queda intacta).

## Contexto

Fase F6: la SPA (React/Vite/TS) tiene datos 100% mock (`src/mocks/*.json`) y contratos en `src/lib/types.ts`. Se introduce un cliente de API tipado que respeta el contrato OpenAPI (SPEC-014) y consume WebChat (SPEC-015), RAG/borrador (SPEC-019) y sentimiento (SPEC-018). El flag permite alternar mock/real por módulo; adaptadores donde el contrato difiera. Base de CE-26 (SPA conectada sin romper el Entregable #1).

## Alcance

### IN
- Cliente de API tipado en la SPA, alineado con el contrato OpenAPI (SPEC-014).
- Feature-flag `VITE_USE_REAL_API` (global y/o por módulo) para alternar mock/real.
- Reemplazo progresivo de mocks: Bandeja (WebChat real), panel RAG (borrador + citas), sentimiento.
- Adaptadores donde el contrato real difiera de `src/lib/types.ts` (documentados).
- Conexión WebSocket real para la Bandeja (SPEC-015) tras el flag.

### OUT
- Endpoints backend en sí (SPEC-014/015/017/018/019).
- Nuevas pantallas/UX no existentes en el Entregable #1.
- Migración de módulos fuera del alcance del slice (voz/ERP/otros canales).

## Dependencias
- Depende de SPEC-014 (OpenAPI), SPEC-015 (WebChat), SPEC-018 (sentimiento) y SPEC-019 (borrador). Consolida la parte frontend del slice.

## Requisitos funcionales
- RF-08 Con `VITE_USE_REAL_API=true`, la SPA consume endpoints reales respetando los contratos.
- RF-05 Con `VITE_USE_REAL_API=false`, la SPA sigue funcionando con mocks (Entregable #1 intacto).
- RF El reemplazo es módulo a módulo y reversible (sin big-bang).
- RF La Bandeja muestra conversaciones/mensajes reales por WebSocket.

## Requisitos no funcionales
- RNF-05 Cambio reversible por feature-flag; sin romper la suite del front.
- RNF-07 Cliente tipado; contratos respetados o adaptador documentado.

## Criterios de aceptación (verificables)
- [ ] Con el flag **off**, la maqueta compila y su suite front pasa igual que en el Entregable #1.
- [ ] Con el flag **on**, la Bandeja muestra conversaciones/mensajes reales (WebChat) del tenant.
- [ ] Con el flag **on**, el panel RAG muestra borrador real con ≥3 citas trazables.
- [ ] Con el flag **on**, el sentimiento real del mensaje se refleja en la UI.
- [ ] El reemplazo de un módulo no rompe los módulos aún en modo mock.
- [ ] Los adaptadores (donde el contrato difiera de `types.ts`) están documentados.

## Notas de seguridad (C2/C3)
- C3: la SPA no embebe secretos; el token se maneja de forma segura (no en el bundle).
- C2: la UI respeta el borrado lógico (no muestra registros inactivos por defecto).

## Restricción SENSIBLE aplicable
- La SPA consume solo APIs on-prem; ninguna llamada de inferencia sale a terceros desde el front.

## Riesgos
- R-25 (migración rompe la SPA): feature-flag reversible + migración módulo a módulo + suite front verde.
- R-23 (mostrar datos cross-tenant): el backend RLS lo impide; la UI usa el token del tenant.

## Checkpoints aplicables
- C2 (borrado lógico en UI). C3 (sin secretos en el bundle). C4 (criterios verificables). C8 (origen PLAN-002).
