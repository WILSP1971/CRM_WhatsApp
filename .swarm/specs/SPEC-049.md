# SPEC-049 — Escalación a humano con contexto + monitor de llamadas en vivo en la SPA (feature-flag) 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: DAREDEVIL, BLACK PANTHER, HAWKEYE, WOLVERINE, BLACK WIDOW · Prioridad: CRÍTICA · Tipo: BACKEND/FRONTEND/CONTROL · Fase: F5
- Deriva de: PLAN-005 (F5, §3.4(b), §2.6, §2.11) · Clasificación: SENSIBLE (`.no-externo`) · reutiliza SPEC-018/020/006/040
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Implementar la **escalación obligatoria a agente humano con contexto** —el guardrail de salida de P1— y el **monitor de llamadas en vivo en la SPA** tras feature-flag. La escalación se dispara ante: (i) intent **fuera de catálogo** o **confianza < umbral** (SPEC-045), (ii) **sentimiento negativo/frustración** (SPEC-018 sobre la transcripción parcial), (iii) **petición explícita** de humano (intent reservado, siempre disponible), (iv) **latencia real por encima del presupuesto de forma sostenida** o alcance del **límite de concurrencia `C`**. La transferencia entrega al agente/cola el **contrato exacto de contexto: transcripción parcial + intent detectado (o "sin intent") + señal de urgencia/sentimiento**, en **≤ N segundos** (RNF-53); el usuario **nunca** queda colgado. El monitor SPA muestra estado/intent y permite transferir/tomar control, sin romper #1-#4 (flag OFF = estado actual intacto).

## Contexto

El human-in-the-loop turno-a-turno (SPEC-019) no aplica a voz en vivo; el Lead lo reemplazó (P1) por catálogo cerrado + **escalación obligatoria**. Esta SPEC define el **contrato de la transferencia** de forma verificable para que el humano retome sin que el cliente repita, y expone el estado en la SPA reutilizando el patrón de feature-flag `VITE_USE_REAL_API` (SPEC-020/031/040) y la vista de VoiceBot/ficha de llamada (SPEC-006/040). El sentimiento negativo reutiliza SPEC-018 sobre la transcripción parcial; el límite `C` y la latencia sostenida provienen del arbitraje de GPU (ADR-011, medido en SPEC-050). La llamada C+1 (por encima de `C`) recibe IVR pregrabado mínimo + escalación (SPEC-044/046), un caso más de esta SPEC.

## Alcance

### IN
- **Motor de escalación** con los 4 disparadores: (i) `SIN_INTENT`/baja confianza (SPEC-045), (ii) sentimiento negativo (SPEC-018), (iii) intent reservado "hablar con una persona", (iv) latencia sostenida sobre presupuesto o límite `C` alcanzado.
- **Contrato exacto de contexto de transferencia** (payload estructurado a la cola/agente): `transcripcion_parcial` (segmentos hasta el momento), `intent_detectado` (o `SIN_INTENT`), `confianza`, `senal_urgencia_sentimiento` (score de SPEC-018 + motivo del disparo), `tenant_id`, `call_id`, timestamp. Versionado y documentado (AsyncAPI, SPEC-052).
- **Enrutamiento a la cola/agente correspondiente** por intent/tenant; si no hay agente disponible, el usuario queda en cola con mensaje pregrabado (nunca colgado sin humano).
- **Handoff de media:** el `voice_gateway` transfiere la sesión de media al agente/cola humana (SPEC-046) al escalar.
- **Monitor de llamadas en vivo en la SPA** tras feature-flag: lista de llamadas activas con estado, intent detectado, señal de urgencia; botón de **transferencia/tomar control** por el agente; consume APIs reales solo con el flag ON (patrón SPEC-020/031/040).
- **Instrumentación:** tiempo desde el disparo hasta la entrega del contexto al agente (para verificar ≤ N s), tasa de escalación por motivo.

### OUT
- Fijación empírica del umbral de latencia sostenida y de `C` (SPEC-050); persistencia/retención de la llamada (SPEC-051); catálogo/NLU (SPEC-045); sentimiento en sí (SPEC-018, reutilizado); despliegue de colas ACD del PBX (fuera de alcance).

## Dependencias
- Depende de SPEC-048 (turno funcional que produce intent/estado), SPEC-045 (intent/umbral), SPEC-018 (sentimiento), SPEC-046 (handoff de media) y SPEC-020 (patrón feature-flag SPA). Reutiliza SPEC-006/040 (vista de VoiceBot/ficha). Prerequisito de SPEC-050 (mide la escalación) y SPEC-051.

## Requisitos funcionales
- RF-01 La escalación se dispara ante los 4 casos (fuera de catálogo/baja confianza, sentimiento negativo, petición explícita, latencia sostenida/límite `C`).
- RF-02 La transferencia entrega el contrato de contexto exacto (transcripción parcial + intent + urgencia/sentimiento) a la cola/agente.
- RF-03 El usuario nunca queda colgado sin humano; si no hay agente, queda en cola con mensaje.
- RF-04 El monitor SPA muestra estado/intent/urgencia y permite transferir/tomar control tras feature-flag (OFF = maqueta/estado actual intacto).
- RF-05 Se mide el tiempo disparo→entrega del contexto (≤ N s) y la tasa de escalación por motivo.

## Requisitos no funcionales
- RNF-53 La escalación entrega el contexto al agente en **≤ N segundos** (valor conservador fijado en esta SPEC y medido en SPEC-050).
- RNF-51 El motor de escalación y el sentimiento son locales, sin egress; el monitor SPA no expone datos cross-tenant (RLS efectiva, ADR-008).
- RNF-07 El flag OFF deja #1-#4 intactos; suites #1-#4 verdes.

## Criterios de aceptación (verificables)
- [ ] Caso `SIN_INTENT`/baja confianza → transferencia con contexto (test HAWKEYE con el simulador).
- [ ] Caso sentimiento negativo (SPEC-018 sobre transcripción parcial) → transferencia con `senal_urgencia_sentimiento` poblada.
- [ ] Caso petición explícita "quiero hablar con una persona" → transferencia inmediata (intent reservado, SPEC-045).
- [ ] Caso latencia sostenida sobre presupuesto / límite `C` alcanzado → escalación (o IVR mínimo + cola para la C+1).
- [ ] El payload de transferencia contiene **transcripción parcial + intent (o SIN_INTENT) + confianza + señal de urgencia/sentimiento + tenant_id + call_id**; validado contra el esquema (AsyncAPI).
- [ ] El tiempo disparo→entrega del contexto es **≤ N s** (medido); el usuario nunca queda colgado (test: sin agente → cola con mensaje).
- [ ] El monitor SPA con flag ON muestra llamadas activas/estado/intent/urgencia y permite transferir/tomar control; con flag OFF, la SPA queda como el estado actual (#1-#4 intactos).
- [ ] Test cross-tenant: el monitor no muestra llamadas de otro tenant (RLS efectiva, ADR-008).

## Notas de seguridad (C2/C3)
- C3: sin secretos en el payload de transferencia/monitor; tokens de la SPA por el mecanismo existente (SPEC-013/020).
- C2: la llamada escalada conserva borrado lógico (hereda `call`/`call_transcript`, SPEC-036).

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress nuevo): el motor de escalación y el sentimiento son locales; el handoff de media lo hace el `voice_gateway` (SPEC-046, único con transporte al PBX). El monitor SPA consume las APIs internas, sin egress de inferencia. El contexto de transferencia (transcripción parcial, posible PHI) se maneja con RLS efectiva por tenant.

## Riesgos
- R-57 (escalación tardía o sin contexto): escalación en ≤ N s con contrato exacto (transcripción+intent+urgencia); intent reservado siempre disponible; casos de prueba (HAWKEYE).
- R-53 (bot fuera de catálogo): fuera de catálogo/baja confianza → transferencia obligatoria (no adivina).
- R-60 (fuga cross-tenant): monitor y payload con RLS efectiva por `tenant_id` (ADR-008); test cross-tenant (SPEC-051).
- R-61 (regresión #1-#4): feature-flag reversible (OFF = estado actual); suites #1-#4 verdes.

## Checkpoints aplicables
- C2 (borrado lógico). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-005).
