# ADR-003 — LLM y embeddings LOCALES (inferencia 100% self-hosted)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-002.md` (F4, IN §5, riesgos R-21/R-27), `SPEC-016` (IA local self-hosted), `SPEC-017` (RAG)

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

El Entregable #2 ("OmniCore AI", fase funcional) requiere **inferencia de IA real** para dos usos:
(a) **borrador de respuesta RAG** con citas trazables (SPEC-017) y (b) **clasificación de sentimiento**
del mensaje entrante (SPEC-018), además de **embeddings** para la recuperación semántica sobre `pgvector`.

El proyecto es **SENSIBLE** (`.no-externo`): está **prohibida cualquier llamada de inferencia a
servicios de terceros** (OpenAI/Anthropic/Google/Cohere u otros). Toda la IA (LLM + embeddings; y a
futuro STT/TTS) debe ser **on-prem, self-hosted, sin salida a internet** (política verificable con
`scripts/puede-modelo-externo.sh` y con la auditoría backend equivalente al `check:externos`).

El hardware del piloto es incierto (pregunta abierta SUP-24 del PLAN-002): puede haber GPU on-prem o no.
Se necesita un runtime y una familia de modelos que corran bien on-prem, den buena calidad en **español
de Colombia** (R-27) y permitan **degradar a CPU** si no hay GPU suficiente (R-21).

---

## Decisión

Se adopta una **pila de inferencia 100% local y parametrizable por variable de entorno**:

| Componente          | Elección por defecto                          | Alternativa / opción                                   | Rol                                                        |
| ------------------- | --------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------- |
| Runtime inferencia  | **Ollama** (simplicidad operativa on-prem)    | **vLLM** (mayor throughput/concurrencia con GPU)       | Servir LLM + embeddings por HTTP en red interna Docker    |
| Modelo generativo   | **Qwen2.5-7B-Instruct** (buen español)        | **Llama-3.1-8B-Instruct**                              | Borrador RAG (SPEC-017) y sentimiento (SPEC-018)          |
| Embeddings          | **nomic-embed-text**                          | **e5** (multilingüe)                                   | Vectorización de chunks/consultas para `pgvector`         |
| Cuantización        | FP16/BF16 con GPU ≥16 GB VRAM                 | **Q4 (cuantizado)** en fallback CPU                    | Ajuste a hardware disponible sin cambiar de familia       |

Reglas de la decisión:

1. **Todo self-hosted:** el runtime corre en el contenedor de IA del `docker-compose`; la API le habla
   por HTTP **interno** (127.0.0.1 / red Docker interna). Ningún flujo de inferencia sale a internet
   (ver **ADR-005** para la garantía técnica de egress bloqueado).
2. **Pesos locales:** los modelos se **descargan y montan como volumen local** (en build o
   aprovisionamiento), **nunca** se hace `pull`/descarga en runtime hacia internet.
3. **Parametrizable por env:** runtime, modelo generativo y modelo de embeddings se seleccionan por
   variables de entorno (`.env.example` sin valores reales), permitiendo cambiar de modelo sin recompilar.
4. **Fallback CPU con Q4:** si no hay GPU ≥16 GB VRAM, se ejecuta el mismo modelo en **CPU con
   cuantización Q4**, aceptando mayor latencia (documentada, ver R-21/CE-23).

---

## Alternativas consideradas

| Alternativa                                                      | Por qué se descartó                                                                                                                                                    |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **APIs externas (OpenAI / Anthropic / Google / Cohere)**        | **PROHIBIDAS** por la clasificación SENSIBLE (`.no-externo`): enviarían datos personales/mensajería a un tercero y ejecutarían inferencia fuera del host. Violan la política de raíz. |
| **Modelos grandes (70B, p. ej. Llama-3.1-70B)**                 | **Inviables** en el hardware del piloto: requieren VRAM/coste muy por encima del dimensionamiento (SUP-24/R-21). Reservados para escala mayor si el volumen lo justifica. |
| **Solo vLLM (sin Ollama)**                                      | vLLM da más throughput con GPU, pero añade fricción operativa en el piloto y no aporta ventaja si se corre en CPU. Se mantiene como **opción** de rendimiento, no como default. |
| **Solo CPU sin GPU como diseño base**                           | Latencia demasiado alta como objetivo por defecto; se conserva únicamente como **fallback** (Q4) cuando no hay GPU disponible.                                          |
| **Embeddings vía API externa**                                  | Misma prohibición SENSIBLE que el LLM; además `pgvector` local exige vectores generados on-prem para no filtrar el corpus.                                              |

---

## Consecuencias

**Pros**

- **Cero dependencia de terceros** para inferencia: cumple SENSIBLE (`.no-externo`) de raíz (CE-21).
- Familia de modelos con **buen español** (Qwen2.5) → mejores borradores/sentimiento en es-CO (R-27).
- **Parametrización por env**: se cambia de modelo/runtime sin tocar código; facilita evaluación.
- El diseño con **pesos locales en volumen** evita cualquier descarga en runtime (apoya ADR-005).

**Cons / mitigaciones**

- **Requisitos de VRAM/latencia**: 7–8B pide GPU ≥16 GB para latencia objetivo → **fallback CPU Q4**
  con degradación **documentada** (R-21); dimensionar por volumen; medición p95 por THOR (CE-23).
- **Gestión de descarga/almacenamiento de pesos**: los pesos ocupan disco y deben aprovisionarse
  localmente → se documenta en el README on-prem qué modelos bajar y dónde montarlos (SPEC-023).
- Calidad del modelo abierto variable → prompts/few-shots afinados y evaluación cualitativa con seed
  por tenant (R-27); modelo intercambiable por env si la calidad no basta.

**Cumplimiento de la restricción SENSIBLE (`.no-externo`)**

- LLM, embeddings y (a futuro) STT/TTS: **100% on-prem**, sin API de terceros.
- Verificación cruzada con **ADR-005** (egress bloqueado + auditoría) y `scripts/puede-modelo-externo.sh`.

**Criterio de verificación (objetivo y verificable)**

- El contenedor de IA sirve LLM y embeddings **solo por HTTP interno**; no existe configuración de
  endpoint de inferencia remoto en código/env (auditado por `check-externos-backend.sh`).
- Los pesos están presentes en **volumen local** antes del arranque; no hay `pull` en runtime.
- RAG e2e produce borrador con **≥3 citas trazables**; **p95 ≤ 6 s** en GPU o degradación CPU documentada (CE-23).

---

## Referencias

- `PLAN-002.md` — F4, alcance IN §5, riesgos **R-21** (GPU/VRAM) y **R-27** (calidad es-CO), CE-21/CE-23.
- `SPEC-016` — IA local self-hosted (Ollama/vLLM + modelo + embeddings + egress auditable).
- `SPEC-017` — Pipeline RAG local con citas trazables. `SPEC-018` — Sentimiento con LLM local.
- Relacionado: **ADR-005** (bloqueo de egress del contenedor de IA), **ADR-004** (aislamiento multi-tenant).
