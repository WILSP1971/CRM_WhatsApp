# ADR-011 — GPU COMPARTIDA priorizada para el VoiceBot en vivo + egress acotado del PBX de media en vivo

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-005.md` (§0, §3.2/§3.3/§3.6/§3.7, F0/F2/F3/F6, riesgos R-51/R-52/R-54/R-59, CE-51/CE-52/CE-55, §11), `SPEC-044`, `SPEC-046`, `SPEC-047`, `SPEC-050`, `SPEC-051`

- **Estado:** Aceptada
- **Fecha:** 2026-09-21
- **Plan:** PLAN-005

---

## Contexto

El Entregable #5 añade el **VoiceBot conversacional EN VIVO** (STT streaming + NLU de catálogo cerrado + TTS
local + barge-in) que el Entregable #4 dejó fuera de alcance. Dos condiciones estructurales del Lead
(2026-09-21, `prompt-lab/PROMPT-OPTIMIZADO-FASE5.md` §8, vinculantes) obligan a decidir arquitectura antes de
implementar:

1. **No hay presupuesto para GPU dedicada adicional (P3).** El VoiceBot en vivo debe **compartir la GPU física**
   con el `stt_worker` batch de #4 (ya en producción, ADR-009). Esto invalida el supuesto orientativo de "GPU
   dedicada" (SUP-55/RNF-53 del prompt de XAVIER). Sin una regla de arbitraje del recurso, ambos cargas degradan
   bajo contención: la voz en vivo (que tiene un presupuesto de latencia percibida ≤700 ms p95, no tolerante a
   cola) y el batch (tolerante a cola por diseño). Una llamada en vivo degradada no es "más lenta": es una
   **llamada rota** para el humano al otro lado.
2. **El audio en vivo llega por un PBX** (on-prem preferido, o proveedor externo). El transporte de media/SIP en
   vivo hacia/desde el PBX es un borde de egress nuevo respecto a #4 (que descargaba grabaciones post-hoc,
   ADR-010). Hay que decidir dónde vive ese borde y garantizar que el STT/TTS/IA **jamás** obtengan esa ruta.

El invariante duro de la clasificación SENSIBLE (ADR-005/ADR-009) sigue intacto: **audio, STT, TTS e inferencia
nunca salen del host**. Lo único que puede salir es el **transporte de media/SIP al PBX**.

Por P-K (supuesto por defecto aprobado), el límite de concurrencia del piloto es **conservador** (`C = 1-3`,
fijado empíricamente por THOR). Por P-D (aprobado), se acepta y se documenta el impacto en el SLA del batch de
#4. Por P-M (aprobado), el PBX se asume **on-prem preferido** (sin egress nuevo); si es externo, aplica egress
acotado análogo a ADR-006/ADR-010.

---

## Decisión

### A. GPU compartida priorizada (P3 vinculante)

1. **GPU física única compartida:** el VoiceBot en vivo (`voice_stt` + `voice_tts` + NLU de intent) y el
   `stt_worker` batch de #4 comparten la misma GPU. **No** se aprovisiona GPU dedicada adicional.
2. **Prioridad estricta de la voz en vivo sobre el batch:** mientras haya **≥1 llamada en vivo activa**, la voz
   en vivo tiene **prioridad** sobre el `stt_worker` batch. Mecanismo (combinable, se fija en SPEC-044/SPEC-050):
   - **(a) Pausa/despriorización del batch:** una señal (lock/flag en Redis) hace que el `stt_worker` batch
     **suspenda o reduzca** su consumo de GPU mientras haya llamadas en vivo; su cola Redis **sigue acumulando**
     y el batch **reanuda** al liberarse la voz (el batch es tolerante a cola por diseño de #4).
   - **(b) Fracción de VRAM reservada** exclusiva para el proceso de voz en vivo, para que la voz tenga memoria
     caliente y no compita por asignación bajo carga.
3. **Modelo STT/TTS liviano en vivo:** el STT en vivo usa un modelo **mucho más liviano que `large-v3`**
   (`distil-whisper` o `faster-whisper` `small`/`medium` cuantizado int8/int8_float16, streaming de ventana
   deslizante); el TTS usa **Piper** (modelo pequeño) o **audios pregrabados** (coste de GPU ~0). Se acepta un
   WER mayor: el camino de voz solo clasifica intent contra un catálogo cerrado, no produce transcripción legal
   (esa se recomputa en batch con `large-v3` de #4 al colgar, sin coste en vivo). Modelo parametrizable por env.
4. **Límite duro de concurrencia `C`:** número máximo de llamadas en vivo simultáneas, **conservador**
   (arranque `C = 1-3`), **fijado empíricamente por THOR** (F6) midiendo con el batch en paralelo. Al llegar la
   llamada **C+1**, **NO se degrada** ninguna llamada activa: la nueva recibe un **IVR pregrabado mínimo +
   escalación a humano** (o cola). El límite es un invariante de calidad, no "best effort".
5. **Degradación documentada + modo bajo-cómputo:** si bajo `C` no se cumple **≤700 ms p95**, se **documenta la
   degradación medida** y se activa el **modo bajo-cómputo** (respuestas del catálogo por **audios
   pregrabados/concatenados**, TTS generativo Piper reservado solo a datos variables), detrás de una **interfaz
   conmutable** por env/feature-flag (sin rediseño). Si ni con modo bajo-cómputo y `C=1` se logra un presupuesto
   aceptable, el alcance se recorta a **IVR de comandos cortos pregrabados** (decisión del Lead), documentando la
   limitación; nunca se sirve una experiencia de voz rota.
6. **Instrumentación de contención:** se mide el tiempo de espera de GPU de la voz y el **backlog del batch
   inducido**, para evidenciar que la prioridad funciona y **cuantificar** el impacto en el SLA del batch de #4
   (impacto aceptado, P-D).

### B. Egress acotado del PBX de media en vivo (análogo a ADR-006/ADR-010)

7. **Egress de media/SIP permitido SOLO desde `voice_gateway`** (red `app`), y **SOLO** hacia el **único host del
   PBX** de media/SIP (allowlist por ruta de módulo, `app/services/telefonia/`). Es **transporte de media**, no
   inferencia ni envío de audio-a-terceros.
8. **STT/TTS/NLU/IA totalmente aislados** (reafirma ADR-005/ADR-009): `voice_stt`, `voice_tts`, NLU de intent,
   `stt_worker` batch e `ia` (Ollama) viven en `ia_internal internal:true`, **nunca** se conectan a `app` con
   egress y **jamás** obtienen ruta al PBX ni a internet. Reciben/entregan audio a través del `voice_gateway`
   por la **red interna**.
9. **Allowlist por RUTA de módulo** en `check-externos-backend.sh`: el host del PBX de media se permite **solo**
   dentro del módulo del `voice_gateway`; en cualquier otro módulo → **falla el CI**. STT/TTS/NLU/IA que importen
   el cliente de transporte de media → **falla** la build; el `voice_gateway` que importe/llame STT/TTS/IA
   directamente (fuera de la red interna/cola) → **falla** la build.
10. **PBX on-prem = sin egress nuevo (topología preferida, P-M):** si el PBX es on-prem (Asterisk/FreeSWITCH),
    este ADR **no habilita ningún egress**; la allowlist pública permanece deshabilitada y el `voice_gateway`
    dialoga con el PBX por la red local. Habilitar egress externo es cambio sensible → aprobación del Lead + C6.
11. **El LLM de dominio abierto (Ollama) NUNCA está en el camino de voz en vivo** (solo enriquecimiento batch
    post-llamada, SPEC-039), reafirmando P1. El camino de voz usa solo STT + NLU de catálogo + TTS.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **GPU dedicada adicional para la voz en vivo** | Descartada por el Lead (P3): **no hay presupuesto**. Es la solución técnica más limpia pero no viable económicamente en el piloto. |
| **Compartir GPU sin regla de prioridad (best effort)** | Bajo contención, **ambos degradan**: la voz en vivo rompe el presupuesto ≤700 ms (llamada rota) y el batch también sufre. Se exige prioridad estricta de la voz + pausa/despriorización del batch. |
| **Priorizar el batch sobre la voz** | Invierte la criticidad: una transcripción batch que tarda unos segundos más es tolerable; una llamada en vivo degradada no lo es. Descartado. |
| **Concurrencia alta de piloto (5-10)** | Asumía GPU dedicada; irreal sobre GPU compartida. Se fija `C` conservador (1-3) empírico por THOR. |
| **Degradar llamadas activas al llegar la C+1** | Rompe conversaciones en curso. Se prefiere IVR mínimo + escalación para la nueva, nunca tocar las activas. |
| **LLM generativo en vivo** | Descartada por P1 (restricción dura de control humano): ningún LLM de dominio abierto habla en vivo. |
| **Que `voice_stt`/`voice_tts`/IA hablen directamente con el PBX** | Daría al STT/TTS/IA ruta a internet/PBX: rompe el aislamiento (ADR-005/ADR-009). El transporte de media es exclusivo del `voice_gateway`. |
| **Dar egress a toda la red `app`** | Amplía superficie innecesariamente; se restringe a `voice_gateway` + allowlist por ruta al host del PBX. |

---

## Consecuencias

**Pros**
- Habilita el VoiceBot en vivo **sin GPU dedicada** ni presupuesto adicional (P3), con una regla de arbitraje
  del recurso que protege el SLA de la voz.
- El batch de #4 sigue funcionando (tolerante a cola) y **reanuda** al liberarse la voz; el impacto se
  **cuantifica y documenta**, no se oculta.
- El audio/STT/TTS/inferencia **nunca salen** (ADR-005/ADR-009 intactos); el único egress posible es el
  transporte de media al PBX, y solo si el PBX es externo.
- Existe un **plan B explícito** (modo bajo-cómputo pregrabado) para que la fase sea viable aunque ≤700 ms no se
  cumpla con TTS generativo.

**Cons / mitigaciones**
- Concurrencia limitada (`C` bajo) → aceptado como coste del piloto (P-K); ampliable solo con GPU adicional
  (decisión futura del Lead).
- Backlog del batch inducido → cuantificado e instrumentado (R-52); el batch reanuda al liberarse la voz;
  `C` se ajusta a la baja si el Lead fija un SLA duro para el batch (P-D).
- Riesgo de que ≤700 ms no se cumpla sobre GPU compartida (R-51) → F6 es la **puerta de viabilidad**; degradación
  documentada + modo bajo-cómputo; recorte a IVR de comandos cortos como último recurso.
- Borde de egress condicional del PBX de media (R-59) → allowlist por ruta, firewall host, prueba de egress vacío
  desde voz/IA + captura de red (SPEC-051). Habilitar egress externo = cambio sensible (aprobación Lead + C6).

**Criterio de verificación (objetivo y verificable)**
- **Prioridad de GPU (CE-52):** con ≥1 llamada en vivo activa, la voz gana GPU y el `stt_worker` batch se
  despriorza/pausa y **reanuda** al liberarse; latencia de voz estable y backlog/recuperación del batch medidos
  (informe THOR, SPEC-050).
- **Latencia (CE-51):** p95 end-to-end **≤ 700 ms** bajo `C` compartiendo GPU con el batch, **o** degradación
  documentada + modo bajo-cómputo activado (SPEC-050).
- **`C` fijado empíricamente** por THOR midiendo con el batch en paralelo; la llamada `C+1` recibe IVR mínimo +
  escalación, sin degradar activas.
- **Egress (CE-55):** un intento de salida desde `voice_stt`/`voice_tts`/NLU/`ia`/`stt_worker` hacia cualquier
  IP/dominio público **falla** (timeout/deny), con evidencia en CI/captura de red (SPEC-051); (si PBX externo)
  el `voice_gateway` alcanza **solo** el host del PBX de media; (si on-prem) **cero** egress público.
- `check-externos-backend.sh` en verde con allowlist por ruta; test negativo (transporte de media fuera del
  `voice_gateway`, o STT/TTS/IA importando el cliente de media) **falla** la build.

---

## Referencias

- `PLAN-005.md` — §0 (P1/P3 vinculantes), §3.2 (invariante de topología), §3.3 (límite de latencia y GPU
  compartida), §3.6 (plan de mitigación de GPU compartida — 4 palancas), §3.7 (aislamiento sin egress), §11
  (ADR-011), §12 (P-K/P-D/P-M), R-51/R-52/R-54/R-59, CE-51/CE-52/CE-55, DoD §3/§4/§5/§8.
- `SPEC-044` — Infra de voz en vivo + GPU compartida priorizada + auditoría de egress.
- `SPEC-046` — Conector de media en vivo (extiende SPEC-037).
- `SPEC-047` — STT streaming liviano en vivo sobre GPU compartida.
- `SPEC-050` — Latencia/GPU compartida (THOR) + fijación de `C` + degradación.
- `SPEC-051` — Seguridad del vector voz/TTS + persistencia + retención.
- Relacionado: **ADR-005** (bloqueo de egress de IA, reafirmado), **ADR-009** (STT local + aislamiento,
  reafirmado y extendido a la voz en vivo), **ADR-010** (egress acotado del PBX externo post-hoc, patrón
  análogo extendido a media en vivo), **ADR-006** (transporte acotado WhatsApp, patrón), **ADR-004/ADR-008**
  (RLS efectiva), **ADR-012** (TTS local + declaración de voz sintética).
- `scripts/check-externos-backend.sh` — auditoría "cero audio/inferencia/TTS a terceros + transporte de media acotado".
