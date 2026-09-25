# ADR-012 — TTS 100% local (Piper/Coqui) + declaración obligatoria de voz sintética

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-005.md` (§1, §3.5/§3.6.4/§3.8, F0/F2/F4/F7, riesgos R-54/R-55, CE-53/CE-55, §11, §12 P-L/P-N), `SPEC-044`, `SPEC-046`, `SPEC-048`, `SPEC-051`

- **Estado:** Aceptada
- **Fecha:** 2026-09-21
- **Plan:** PLAN-005

---

## Contexto

El Entregable #5 introduce un vector SENSIBLE **nuevo** que no existía en #4: la **voz sintética de salida (TTS)
que habla en nombre de la empresa en tiempo real**. Dos dimensiones de riesgo:

1. **Superficie de datos personales / dependencia externa.** Sintetizar la respuesta con un TTS en la nube
   (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS, Coqui-cloud, etc.) implicaría enviar a un
   tercero **el contenido que la empresa dice al cliente** (con posibles datos personales/PHI en las plantillas
   rellenadas: nombre, estado de cita, etc.) y crear una dependencia externa en el camino de voz. Rompe SENSIBLE
   (`.no-externo`) igual que enviar el audio de entrada a un STT de terceros (ADR-009).
2. **Riesgo de voz sintética engañosa / deepfake regulatorio.** Una voz que suena humana hablando en nombre de la
   empresa sin que el usuario sepa que es un bot es un riesgo legal y reputacional (Ley 1581 / normativa de IA
   conversacional; §7 P-L). El usuario debe saber que habla con un asistente virtual.

Por **P-L** (supuesto por defecto aprobado), se declara **siempre** que el interlocutor es un asistente virtual,
independientemente de si la ley lo exige explícitamente (buena práctica anti-deepfake + mitigación reputacional).
Por **P-N** (aprobado), por defecto **no se persiste** el audio TTS de salida (se persiste la transcripción
textual de lo que dijo el bot); si se persiste, aplica la retención/anonimización de #4 (SPEC-041/ADR-009).

Este ADR **extiende ADR-009** (que ya prohibía STT de terceros y anticipaba "cualquier TTS futuro") al vector TTS
ahora que se materializa.

---

## Decisión

1. **TTS 100% local (self-hosted):** la síntesis de voz usa **Piper** (voz es-CO, o la voz más cercana
   disponible) como motor por defecto; **Coqui** como alternativa evaluada por THOR (F6). **TTS de terceros
   PROHIBIDO** en todo el código (Google TTS, AWS Polly, ElevenLabs, Azure Speech, OpenAI TTS, Coqui-cloud,
   Deepgram TTS, PlayHT, etc.), mismo criterio que STT en ADR-009, verificado en `check-externos-backend.sh`
   (SPEC-044/SPEC-051). Los **pesos/voces se montan por volumen** (sin `pull`/descarga en runtime).
2. **`voice_tts` aislado sin egress:** el `voice_tts` vive en `ia_internal internal:true` (comparte el
   aislamiento de la IA, ADR-005/ADR-009/ADR-011). **Nunca** se le añade la red `app` ni ruta a internet ni al
   PBX. Entrega el audio sintetizado al `voice_gateway` por la **red interna**, no por red externa.
3. **Interfaz de TTS conmutable (Piper generativo ↔ banco de audios pregrabados):** el TTS se implementa detrás
   de una interfaz conmutable por env/feature-flag (§3.6.4), de modo que el **modo bajo-cómputo** (respuestas del
   catálogo cerrado por audios pregrabados/concatenados, coste de GPU ~0) **no** requiera rediseño. El TTS
   generativo Piper se reserva a respuestas con datos variables no pregrabables. El **banco de audios pregrabados
   se monta por volumen**.
4. **Declaración obligatoria de voz sintética al inicio de CADA llamada:** un mensaje pregrabado declara al
   usuario que el interlocutor es un **asistente virtual** antes de cualquier interacción del catálogo. Se declara
   **siempre** (P-L), independientemente de la exigencia legal explícita. Es un invariante verificable (SPEC-046).
5. **Retención del audio TTS:** por defecto **NO se persiste** el audio de salida (P-N); se persiste la
   **transcripción textual** de lo que dijo el bot (queda en `call_transcript`, SPEC-036). Si por auditoría se
   decide persistir el audio TTS, aplica la política de retención/anonimización de #4 (SPEC-041/ADR-009): cifrado
   en reposo, retención configurable, purga/anonimización, acceso auditado.
6. **Voz Piper estándar, NO clonada:** no se clona ni personaliza la voz de una persona real (clonación fuera de
   alcance, OUT del PLAN-005), reduciendo el riesgo de suplantación.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **TTS en la nube (Google TTS / AWS Polly / ElevenLabs / Azure Speech / OpenAI TTS)** | Enviaría a un tercero el **contenido que la empresa dice** (con posibles datos personales/PHI) y crearía dependencia externa en el camino de voz: rompe SENSIBLE/`.no-externo` (igual que STT de terceros, ADR-009). Prohibido. |
| **`voice_tts` en la red `app` (con egress) por comodidad** | Superficie de salida innecesaria: el TTS no necesita internet ni el PBX (entrega el audio al `voice_gateway` por la red interna). Aumenta R-54. Descartado a favor de `ia_internal internal:true`. |
| **No declarar que es voz sintética** | Riesgo legal/reputacional (deepfake, engaño al usuario, Ley 1581 / normativa de IA); R-55. Se declara siempre (P-L). |
| **Clonar/personalizar la voz de una persona real** | Riesgo de suplantación y superficie de deepfake mucho mayor; fuera de alcance (OUT). Voz Piper estándar. |
| **Solo TTS generativo (sin modo pregrabado)** | Ata la viabilidad de latencia (≤700 ms sobre GPU compartida) a que Piper quepa en el presupuesto; sin plan B. Se exige interfaz conmutable con banco pregrabado (ADR-011 §5, §3.6.4). |
| **Persistir siempre el audio TTS** | Aumenta la superficie SENSIBLE sin necesidad (basta la transcripción textual). Por defecto no se persiste (P-N); si se persiste, retención de #4. |

---

## Consecuencias

**Pros**
- La voz de salida y su contenido **nunca salen** del host: cumple SENSIBLE sin excepción; extiende ADR-009 al
  vector TTS.
- El usuario **sabe** que habla con un bot (declaración obligatoria): mitiga riesgo deepfake/legal (R-55).
- La interfaz conmutable habilita el **modo bajo-cómputo pregrabado** sin rediseño (clave para la viabilidad de
  latencia sobre GPU compartida, ADR-011).
- Menor superficie SENSIBLE al **no persistir** el audio TTS por defecto (P-N).

**Cons / mitigaciones**
- Piper es-CO puede sonar menos natural que un TTS comercial → aceptado; la naturalidad no es requisito de la
  fase, la privacidad sí; Coqui evaluado como alternativa (THOR).
- El TTS generativo consume GPU compartida (R-51/R-52) → modo bajo-cómputo pregrabado (coste ~0) + interfaz
  conmutable; TTS Piper reservado a datos variables (ADR-011 §5).
- Gestión de pesos/voces y del banco de audios por volumen → runbook + secretos en env (C3, SPEC-052).
- Si se decide persistir el audio TTS → cambio sensible, aplica retención de #4 (SPEC-041) + aprobación Lead (C6).

**Criterio de verificación (objetivo y verificable)**
- **TTS local (CE-55):** las respuestas se sintetizan 100% local; un intento de egress desde `voice_tts` a
  cualquier IP/dominio público **falla** (timeout/deny), con evidencia en CI/captura de red (SPEC-051).
- `check-externos-backend.sh` en verde con **TTS de terceros prohibido** (test negativo: insertar `elevenlabs`,
  `aws-polly`, `azure.*speech`, `openai.*audio.*speech`, `google.*texttospeech`, etc. **falla** la build).
- **Declaración de voz sintética (CE-53):** al inicio de cada llamada suena el mensaje que declara el asistente
  virtual antes de cualquier interacción del catálogo (test verificable con el simulador, SPEC-046/SPEC-052).
- **Interfaz conmutable (CE-51):** conmutar TTS generativo ↔ banco pregrabado por env no requiere cambios de
  código en el orquestador de diálogo (SPEC-048/SPEC-050).
- **Retención (CE-55):** por defecto el audio TTS no se persiste; si se persiste, aplica la retención/anonimización
  de SPEC-041/ADR-009 (SPEC-051).

---

## Referencias

- `PLAN-005.md` — §1 (TTS de salida como vector SENSIBLE nuevo), §3.5 (voz sintética de salida), §3.6.4
  (interfaz conmutable / modo bajo-cómputo), §3.8 (auditoría TTS de terceros), §11 (ADR-012), §12 (P-L/P-N),
  R-54/R-55, CE-51/CE-53/CE-55, DoD §3/§6/§7.
- `SPEC-044` — Infra: `voice_tts` en `ia_internal` sin egress + banco de audios pregrabados por volumen +
  `check-externos-backend.sh` extendido (TTS de terceros prohibido).
- `SPEC-046` — Conector de media en vivo: declaración de voz sintética al inicio de cada llamada.
- `SPEC-048` — Bucle de diálogo: TTS Piper o modo bajo-cómputo (interfaz conmutable) + barge-in.
- `SPEC-051` — Seguridad del vector voz/TTS + retención (reutiliza SPEC-041).
- Relacionado: **ADR-009** (STT local + aislamiento, extendido al vector TTS), **ADR-005** (bloqueo de egress de
  IA, reafirmado), **ADR-011** (GPU compartida priorizada + egress acotado del PBX de media).
- `scripts/check-externos-backend.sh` — auditoría "cero audio/inferencia/TTS a terceros".
