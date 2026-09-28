# SPEC-071 — Pruebas + seguridad + no-regresión: e2e opt-in, cero egress de voz, ningún audio sin aprobación, cero regresión #4/#5/texto, latencia/coste CPU (THOR), cobertura ≥80% 🔴 SENSIBLE

- Estado: APROBADA · Responsable: HAWKEYE · Colaboran: BLACK WIDOW, WOLVERINE, THOR, BLACK PANTHER, CAPTAIN AMERICA, DAREDEVIL · Prioridad: ALTA · Tipo: QA/SEGURIDAD/PERF · Fase: F4
- Deriva de: PLAN-008 (F4, §2.IN.10, §4, §6 R-81/R-82/R-84/R-86, CE-81..CE-86) · Clasificación: SENSIBLE (`.no-externo`) · ADR-014/ADR-005/ADR-006/ADR-009/ADR-012
- APROBADO SPEC-071 por el Lead (bloque PLAN-008) — 2026-09-28.

## Objetivo

Verificar, de forma **objetiva y automatizada**, que el slice del Entregable #6 cumple sus invariantes: **e2e opt-in** (guion aprobado → audio generado local → subido por WhatsApp, en ambas rutas híbridas); **cero egress de voz** (TTS de terceros prohibido, `check-externos-backend.sh` verde, egress vacío desde el servicio TTS en `ia_internal`); **ningún audio enviado sin aprobación humana** (guion o clip escuchado); **cero regresión** del flujo de texto (SPEC-029), del pipeline de nota de voz entrante #5 (SPEC-053..061) y de los jobs `call` de #4; **latencia/coste de CPU dentro de lo medido por THOR** (SPEC-067); accesibilidad AAA de la UX de audio; y **cobertura del código nuevo ≥80%**.

## Contexto

Reúne los criterios verificables del plan (CE-81..CE-86) en una suite ejecutable, sobre lo entregado por SPEC-067..070. La barrera de egress ya está activa y en verde hoy sin código TTS: `backend/check-externos-backend.sh` bloquea TTS de terceros por dominio (ElevenLabs, Polly, Google/Azure/OpenAI TTS, PlayHT, Deepgram, Coqui-cloud) y por SDK, y **debe seguir verde** al añadir TTS local (que es on-prem, sin dominio externo). Las suites de #4 (jobs `call`) y #5 (nota de voz entrante e2e, SPEC-060) existen y deben pasar **sin modificar sus asserts** (patrón de no-regresión ya usado en SPEC-056/060). El dimensionado de throttling/concurrencia y el techo de latencia provienen de SPEC-067 (THOR): esta SPEC verifica que la implementación de SPEC-069 los respeta bajo carga concurrente con STT batch/RAG/sentimiento.

## Alcance

### IN
- **E2E opt-in (ambas rutas híbridas):**
  - Ruta por defecto: aprobar el guion con `respuesta_modo="audio"` → clip generado local → subido por `app/integrations/whatsapp/`; verificado extremo a extremo con simulador (SPEC-072), sin egress de voz.
  - Ruta "escuchar antes de enviar": clip generado bajo demanda → aprobación explícita del audio → envío; sin aprobación, no hay envío.
- **Test negativo de aprobación (CE-81):** un intento de envío de audio **sin** guion/clip aprobado **falla**; se cubren ambas rutas.
- **Cero egress de voz (CE-82):** test de egress vacío desde el servicio TTS en `ia_internal` (intento de salida a IP/dominio público **falla**); `check-externos-backend.sh` en verde con TTS de terceros prohibido (test negativo: introducir un dominio/SDK TTS prohibido **rompe** la build); el servicio TTS **no** importa/ejecuta el cliente de subida.
- **Cero regresión (CE-83):** las suites de respuesta en texto (SPEC-029), de nota de voz entrante #5 (SPEC-053..061, incl. SPEC-060) y de un job `call` de #4 pasan **sin modificar asserts**; e2e de no-regresión de un WhatsApp de texto y de una nota de voz entrante.
- **Opt-in + aditivo (CE-85):** por defecto la respuesta es texto (`respuesta_modo="texto"`); la migración es aditiva/nullable (SPEC-068); el clip se sube **solo** por el módulo WhatsApp; por defecto **no** queda clip persistido (test de no-persistencia).
- **Latencia/coste de CPU (CE-84/CE-86, THOR):** medición de latencia del clip dentro del techo de SPEC-067; medición del impacto del TTS encolado con throttling sobre STT batch/RAG/sentimiento concurrentes, comparado con el umbral de SPEC-067; verificación de que la concurrencia limitada se respeta.
- **Seguridad (BLACK WIDOW):** RLS efectiva sobre los nuevos campos (cross-tenant que falla por RLS); ausencia de secretos/PII en logs (C3); retención/cifrado del clip si se persiste por auditoría (SPEC-041); disclaimer presente (CE-87, coordinado con SPEC-070).
- **Accesibilidad AAA (CE-87 UX):** auditoría de la UX de audio (estados, reproductor, disclaimer) con contraste ≥7:1, teclado y anuncios accesibles.
- **Cobertura ≥80%** del código nuevo (servicio TTS, integración de aprobación, SPA de audio).

### OUT
- Implementación del servicio/UX (SPEC-069/070), decisión de motor (SPEC-067), ADR/datos/config (SPEC-068).
- Docs/runbook/deploy (SPEC-072).
- Definir el techo de latencia/throttling (lo fija SPEC-067; aquí se **verifica** que se respeta).

## Dependencias
- Depende de SPEC-067 (techo/throttling de referencia), SPEC-068 (modelo/config), SPEC-069 (servicio/envío) y SPEC-070 (SPA/disclaimer). Reutiliza `check-externos-backend.sh`, la suite de #5 (SPEC-060) y las suites de #4/texto. Se ancla en ADR-005/006/009/012/014. Prerequisito de SPEC-072 (deploy).

## Requisitos funcionales
- RF-01 E2E opt-in verde en ambas rutas híbridas (guion por defecto y escuchar antes de enviar).
- RF-02 Test negativo: envío de audio sin aprobación (guion o clip) **falla** en ambas rutas.
- RF-03 Cero egress de voz: egress vacío desde el servicio TTS; `check-externos-backend.sh` verde; test negativo de dominio/SDK TTS prohibido rompe la build.
- RF-04 Cero regresión: suites de texto (SPEC-029), #5 (SPEC-053..061) y un job `call` de #4 pasan sin modificar asserts.
- RF-05 Opt-in/aditivo: default texto; migración aditiva; subida solo por módulo WhatsApp; no-persistencia por defecto verificada.
- RF-06 Latencia/coste CPU dentro de lo medido por SPEC-067 (THOR) bajo carga concurrente.
- RF-07 RLS efectiva sobre los nuevos campos (cross-tenant que falla); sin secretos/PII en logs; disclaimer presente; accesibilidad AAA.

## Requisitos no funcionales
- RNF-COV Cobertura del código nuevo ≥80%.
- RNF-01 La suite corre sin egress (salvo el transporte WhatsApp simulado); no introduce dependencias externas de voz.
- RNF-84 Verifica el umbral de coste CPU concurrente fijado por SPEC-067.
- RNF-C2/C3 Verifica borrado lógico/purga del clip (si se persiste) y ausencia de secretos/PII en logs/artefactos.

## Criterios de aceptación (verificables)
- [ ] E2E opt-in verde en ambas rutas (guion por defecto y escuchar antes de enviar), con simulador y sin egress de voz.
- [ ] Envío de audio **sin** guion/clip aprobado **falla** (test negativo, ambas rutas).
- [ ] Egress vacío desde el servicio TTS en `ia_internal`; `check-externos-backend.sh` verde; introducir un dominio/SDK TTS prohibido **rompe** la build; el servicio TTS no importa el cliente de subida.
- [ ] Suites de texto (SPEC-029), #5 (SPEC-053..061) y un job `call` de #4 pasan **sin modificar asserts**.
- [ ] Default `respuesta_modo="texto"`; migración aditiva; clip subido solo por el módulo WhatsApp; **no** queda clip persistido por defecto.
- [ ] Latencia del clip dentro del techo de SPEC-067; el TTS encolado con throttling no degrada STT batch/RAG/sentimiento por encima del umbral THOR; concurrencia limitada respetada.
- [ ] Cross-tenant sobre los nuevos campos **falla** por RLS; sin secretos/PII en logs; disclaimer presente; auditoría AAA de la UX de audio pasa.
- [ ] Cobertura del código nuevo ≥80%.

## Notas de seguridad (C2/C3)
- C2: verifica que por defecto no hay clip persistido; si se persiste por auditoría, respeta borrado lógico/purga física (SPEC-041/058).
- C3: verifica ausencia de secretos/PII en logs y artefactos de prueba; guiones/fixtures ficticios.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el corazón de la SPEC es la **evidencia auditable** de cero egress de voz (test negativo + captura + script verde) y de aislamiento del servicio TTS en `ia_internal`. La única salida es el transporte WhatsApp (`graph.facebook.com`, ADR-006), simulado en las pruebas; ningún TTS de terceros (ADR-012).

## Riesgos
- R-81 (fuga de egress de voz): cubierto por test de egress vacío + `check-externos-backend.sh` + test negativo de dominio/SDK; verificación de que el servicio no importa el cliente de subida. **Top-1.**
- R-82 (regresión #4/#5/texto): suites existentes sin modificar asserts + e2e de no-regresión.
- R-84 (coste CPU): medición concurrente contra el umbral THOR (SPEC-067).
- R-86 (retención/PHI del clip): test de no-persistencia por defecto; cifrado/purga si se persiste.

## Checkpoints aplicables
- C2 (borrado lógico/purga). C3 (sin secretos/PII en logs). C4 (criterios verificables). C6 (validación previa a deploy sensible). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
