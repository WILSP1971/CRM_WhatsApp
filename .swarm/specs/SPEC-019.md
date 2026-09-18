# SPEC-019 — Borrador RAG human-in-the-loop: revisar / editar / aprobar antes de enviar

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: ALTA · Tipo: BACKEND/FLUJO · Fase: F5
- Deriva de: PLAN-002 (F5) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Ofrecer al agente el **borrador RAG** (SPEC-017) para que lo **revise, edite y apruebe** antes de enviarlo al visitante: **nada se envía autónomamente**; el envío requiere acción humana explícita.

## Contexto

Fase F5: el borrador citado generado localmente se presenta al agente en la Bandeja. El agente decide (aprobar tal cual, editar, o descartar). Solo tras la aprobación humana el mensaje se envía por el canal real (SPEC-015) y se persiste. Refuerza el requisito de PLAN-002 de que la IA no auto-responde en este slice. El render del flujo en la SPA se completa en SPEC-020.

## Alcance

### IN
- Endpoint que devuelve el borrador RAG (texto + citas) para una conversación/mensaje.
- Estados del borrador: `propuesto` → `editado` → `aprobado` / `descartado`.
- Edición del borrador por el agente antes de aprobar (se conserva el texto final).
- Envío SOLO tras aprobación humana explícita; se persiste el mensaje enviado y su origen (borrador).
- Trazabilidad: se registra que el mensaje enviado provino de un borrador aprobado (auditoría).

### OUT
- Generación del borrador y sus citas (SPEC-017).
- Sentimiento (SPEC-018).
- Auto-respuesta autónoma de la IA (explícitamente OUT en PLAN-002).
- Render del flujo en la SPA (SPEC-020).

## Dependencias
- Depende de SPEC-017 (borrador RAG citado) y SPEC-015 (canal para el envío). Prerequisito de SPEC-020 (render).

## Requisitos funcionales
- RF-07 El agente recibe un borrador citado y puede aprobar/editar/descartar.
- RF Nada se envía al visitante sin aprobación humana explícita.
- RF El mensaje enviado se persiste indicando que provino de un borrador aprobado.
- RF La edición del agente se conserva como texto final enviado.

## Requisitos no funcionales
- RNF-02 Aislamiento por tenant en borradores y envíos.
- RNF-06 Trazabilidad/auditoría del origen del mensaje (borrador → aprobado → enviado).

## Criterios de aceptación (verificables)
- [ ] El endpoint devuelve el borrador RAG (texto + ≥3 citas) para la conversación del tenant.
- [ ] Ningún borrador se envía al visitante sin una acción de aprobación humana explícita.
- [ ] Un borrador editado por el agente envía el texto final editado (no el original).
- [ ] Un borrador descartado no genera ningún envío ni mensaje persistido de salida.
- [ ] El mensaje enviado registra su origen (borrador aprobado) para auditoría.
- [ ] Los borradores de un tenant no son accesibles por otro tenant (RLS).

## Notas de seguridad (C2/C3)
- C2: borradores/mensajes con borrado lógico (Activo/Inactivo).
- C3: config SOLO en env.

## Restricción SENSIBLE aplicable
- Human-in-the-loop obligatorio; la IA no auto-responde. Generación 100% local (cero externos).

## Riesgos
- R-27 (calidad del borrador): edición humana obligatoria antes de enviar.
- R-23 (fuga cross-tenant): RLS + test cross-tenant (SPEC-022).

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-002).
