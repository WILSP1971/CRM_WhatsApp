# SPEC-045 — Catálogo cerrado de intents + NLU determinista (sin LLM generativo en vivo) 🔵 SENSIBLE

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, WOLVERINE · Prioridad: CRÍTICA · Tipo: BACKEND/NLU/CONTROL · Fase: F1
- Deriva de: PLAN-005 (F1, §0 P1, §3.4, §3.6.2) · Clasificación: SENSIBLE (`.no-externo`) · reafirma ADR-003/ADR-011/ADR-012
- Pendiente de aprobación explícita del Lead (no aprobar la propia SPEC).

## Objetivo

Definir e implementar el **catálogo cerrado de intents pre-aprobado** como artefacto de configuración versionado (no editable en runtime por el bot) y el **motor de clasificación de intent DETERMINISTA por embeddings/pgvector** (reutiliza SPEC-014..017, `nomic-embed`) con **umbral de confianza**, garantizando que **NINGÚN LLM generativo** entra al camino de voz en vivo (restricción dura del Lead P1, §3.6.2). Cada intent declara nombre, ejemplos de frases, respuesta permitida (anclada a RAG con citas SPEC-017 o a audio pregrabado) y acción (responder / consultar dato / agendar / **transferir**). Se incluye el intent reservado **"hablar con una persona"** siempre disponible. Por debajo del umbral o sin match → **transferencia** (contrato de escalación en SPEC-049).

## Contexto

El human-in-the-loop turno-a-turno de #2/#3/#4 (SPEC-019, aprobar cada frase) **no es trasladable** a voz en vivo. El Lead aprobó (P1, vinculante) reemplazarlo por **"guardrails antes, no aprobación durante"**: el bot solo puede decir lo que el catálogo cerrado permite, y **transfiere a humano** ante cualquier cosa fuera de él. Esta SPEC es la **puerta del control humano** de la fase: sin catálogo cerrado no hay diálogo permitido. El motor de intent **reutiliza el mismo stack de embeddings/pgvector** ya en producción (SPEC-014..017) — no se introduce un modelo nuevo ni un LLM generativo. El catálogo del piloto usa el mínimo aprobado en P-C: (i) consulta de estado de pedido/cita, (ii) agendar/reagendar/cancelar cita, (iii) FAQ desde la base de conocimiento RAG existente, (iv) intent reservado "hablar con una persona"; todo lo demás → transferencia.

## Alcance

### IN
- **Esquema del catálogo cerrado** (artefacto versionado en repo, p. ej. YAML/JSON revisado por humano): por intent → `nombre`, `ejemplos[]` (frases para embeddings), `respuesta` (plantilla anclada a RAG con citas SPEC-017 **o** referencia a audio pregrabado), `accion` (`responder` | `consultar_dato` | `agendar` | `transferir`), `umbral_min?` (override por intent).
- **Precómputo de embeddings** de los ejemplos del catálogo con `nomic-embed` (SPEC-016) e indexado en pgvector (SPEC-017), por tenant si el catálogo es multi-tenant.
- **Clasificador de intent determinista:** dada una transcripción parcial, calcula similitud de embeddings contra los ejemplos del catálogo; devuelve `intent + score`. `score ≥ umbral` → intent aceptado; `score < umbral` o sin match → resultado `SIN_INTENT` (dispara transferencia en SPEC-049).
- **Intent reservado "hablar con una persona"** siempre presente y con prioridad (frases explícitas de petición de humano → transferencia inmediata, independientemente del score de otros intents).
- **Umbral de confianza** parametrizable por env/config (global y override por intent); documentado y ajustable sin redeploy de imagen.
- **Validación de "sin LLM generativo en el camino de voz":** el módulo de NLU de intent NO importa ni invoca el LLM generativo (`ia`/Ollama) para clasificar ni para generar texto de respuesta libre; verificable en CI (§3.8.5 del PLAN).
- Seed ficticio del catálogo del piloto (4 intents mínimos, P-C) con ejemplos es-CO.

### OUT
- Orquestación del turno (clasificar → responder → TTS) y barge-in (SPEC-048); contrato exacto de la transferencia a humano (SPEC-049); STT streaming que produce la transcripción parcial (SPEC-047); medición de latencia del NLU (SPEC-050).
- Edición del catálogo desde la SPA (fuera de alcance; el catálogo se cambia por config revisada, no en runtime).

## Dependencias
- Depende de SPEC-044 (infra NLU en `ia_internal`), SPEC-016 (embeddings `nomic-embed` locales) y SPEC-017 (RAG con citas/pgvector). Prerequisito de SPEC-048 (bucle de diálogo) y SPEC-049 (escalación). Se ancla en ADR-003 (LLM/embeddings locales) y ADR-011 (ningún LLM generativo en vivo).

## Requisitos funcionales
- RF-01 Existe un artefacto de catálogo cerrado versionado con el esquema definido; no editable por el bot en runtime.
- RF-02 El clasificador devuelve `intent + score` por embeddings; `score < umbral` o sin match → `SIN_INTENT`.
- RF-03 El intent "hablar con una persona" está siempre disponible y transfiere de inmediato.
- RF-04 El umbral de confianza es parametrizable (global y por intent).
- RF-05 El NLU de intent NO usa un LLM generativo para clasificar ni para producir texto libre.

## Requisitos no funcionales
- RNF-53 Clasificación determinista y barata (embeddings, sin generación): apta para el presupuesto de latencia por turno (medida en SPEC-050).
- RNF-51 NLU 100% local sin egress (hereda SPEC-044/ADR-011).
- RNF-47 Si el catálogo es multi-tenant, sus embeddings respetan el aislamiento por `tenant_id` (RLS efectiva, ADR-008).

## Criterios de aceptación (verificables)
- [ ] El catálogo cerrado existe como artefacto versionado con el esquema (`nombre`, `ejemplos`, `respuesta`, `accion`, `umbral_min?`); un test valida el esquema.
- [ ] Frases de ejemplo dentro de catálogo clasifican al intent correcto con `score ≥ umbral`; frases fuera de catálogo devuelven `SIN_INTENT` (test con set es-CO ficticio).
- [ ] Una frase de petición explícita de humano ("quiero hablar con una persona") resuelve al intent reservado y marca transferencia inmediata.
- [ ] Bajar el umbral hace clasificar más frases; subirlo produce más `SIN_INTENT` (parametrización verificada).
- [ ] **Verificación en CI de que el NLU de intent no importa/invoca el LLM generativo** (`ia`/Ollama) en el camino de voz en vivo: introducir esa dependencia **falla** la build.
- [ ] Los embeddings del catálogo se precomputan e indexan; recalcularlos es reproducible y no requiere internet.
- [ ] Seed ficticio del catálogo del piloto disponible (4 intents mínimos, P-C); sin datos reales/secretos; suites #1-#4 verdes.

## Notas de seguridad (C2/C3)
- C2: el catálogo es config versionada; sus cambios quedan trazados en control de versiones (no borrado físico de datos de negocio).
- C3: sin secretos en el catálogo/seed; solo placeholders y frases ficticias.

## Restricción SENSIBLE / excepción de egress
- 🔵 SENSIBLE (sin egress): el NLU de intent es 100% local (embeddings en `ia_internal`, sin salida). Restricción dura P1: **ningún LLM generativo habla en vivo**; el catálogo cerrado + escalación es el invariante de control humano de la fase.

## Riesgos
- R-53 (el bot habla fuera del catálogo): NLU determinista por embeddings con umbral; ningún LLM generativo en vivo (verificado en CI); fuera de catálogo/baja confianza → transferencia obligatoria (SPEC-049).
- R-58 (WER alto degrada la clasificación): el catálogo cerrado tolera transcripción imperfecta mejor que un resumen; umbral + escalación ante baja confianza (no adivina); transcripción de calidad recomputada en batch (`large-v3` de #4).
- R-60 (fuga cross-tenant): si el catálogo/embeddings son multi-tenant, RLS efectiva por `tenant_id` (ADR-008); test cross-tenant (SPEC-051).

## Checkpoints aplicables
- C2 (config versionada / borrado lógico del stack). C3 (sin secretos). C4 (criterios verificables). C8 (origen PLAN-005).
