# SPEC-003 — Layout global y navegación SPA

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, WOLVERINE, HAWKEYE · Prioridad: ALTA · Tipo: FUNDACIONAL · Fase: F2
- Deriva de: PLAN-001 (F2) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Construir el chasis de la aplicación: sidebar plegable con los 6+ espacios, header global
(búsqueda semántica simulada, widget estado VoiceBot, selector de inquilino, notificaciones,
perfil) y routing SPA entre módulos, sobre los tokens y temas de SPEC-002.

## Contexto

Todos los módulos (SPEC-004 a SPEC-008) viven dentro de este layout/router. Es prerrequisito
de esas SPECs. La navegación es SPA sin recargas.

## Alcance

### IN

- Sidebar plegable persistente: Bandeja unificada, Contactos 360°, Centro de llamadas VoiceBot, Centro RAG, Sync ERP, Flujos automatizados, Analítica multisectorial.
- Header: búsqueda semántica global (resultados mock categorizados), widget estado VoiceBot, selector de inquilino/empresa (cambia branding/nombre), notificaciones, menú de perfil.
- Router SPA entre módulos con estado activo/hover visible; toggle de tema en el header.
- Estados vacíos/placeholder para módulos aún no implementados.

### OUT

- Contenido funcional de cada módulo (SPEC-004 a SPEC-008); aislamiento real multi-tenant.

## Dependencias

- Depende de SPEC-001 y SPEC-002. Prerrequisito de SPEC-004 a SPEC-008.

## Requisitos funcionales

- RF-01 Navegación entre los 6 espacios sin recargar, con estado activo/hover.
- RF-02 Sidebar se pliega/despliega y persiste su estado durante la sesión.
- RF-08 Búsqueda global despliega resultados mock categorizados (contactos, conversaciones, docs RAG).
- RF-09 Selector de inquilino cambia branding/nombre visible.
- RF Widget de estado VoiceBot y panel de notificaciones desplegables (mock).

## Requisitos no funcionales

- Estilos 100% desde tokens (RNF-04). Sin scroll horizontal 1280–1920 (RNF-03).
- Interacciones <100 ms; animaciones de sidebar/paneles a 60 fps.

## Criterios de aceptación (verificables)

- [ ] Los 6+ items del sidebar navegan a su ruta sin recargar y marcan estado activo.
- [ ] El sidebar se pliega/despliega y conserva su estado tras navegar.
- [ ] La búsqueda global muestra resultados mock en ≥3 categorías.
- [ ] El selector de inquilino cambia el nombre/branding visible.
- [ ] Sin scroll horizontal ni solapamientos entre 1280px y 1920px.
- [ ] Cero errores de consola en el recorrido, ambos temas.

## Accesibilidad (WCAG 2.2 AAA)

- Landmarks (`nav`, `header`, `main`); skip-link al contenido principal.
- Navegación completa por teclado con foco visible en sidebar, header y menús.
- Sidebar colapsable operable por teclado; `aria-expanded`/`aria-current` correctos.
- Contraste AAA ≥7:1 en textos e íconos de navegación en ambos temas.

## Restricción SENSIBLE

- Cero llamadas externas: búsqueda, notificaciones y tenants son mock locales.
- Cero PII real: nombres de inquilinos/contactos ficticios.

## Riesgos

- R-04 (performance de animaciones): animaciones GPU-friendly, medir en F7.
- R-07 (deriva): revisión de tokens WOLVERINE.

## Checkpoints aplicables

- C4 (criterios verificables). C8 (origen registrado).
