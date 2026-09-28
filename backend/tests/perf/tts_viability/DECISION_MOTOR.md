# Decisión de motor TTS — SPEC-067 (THOR)

Estado: evidencia recolectada y decisión propuesta por THOR. **Sujeta a aprobación del Lead**
(ADR-014 formaliza la decisión firme, ver SPEC-067 RNF-DECISION).

## 1. Motor elegido

**Piper TTS**, versión `piper-tts==1.8.0`, voz **`es_ES-davefx-medium`**, parámetros por
defecto de `SynthesisConfig()` (sin ajuste de `length_scale`/`noise_scale`), ejecutado con
`use_cuda=False`, cargado UNA VEZ por proceso worker (patrón "warm", no invocar el CLI por
petición).

### Por qué Piper y no Coqui

1. **Latencia**: Piper (`es_ES-davefx-medium`) es la única combinación motor+voz evaluada que
   cumple el techo `<=10s` en las 8 categorías de guión (peor caso p95 = 7.19s en el párrafo
   más largo) y además cumple `<=5s` en 6 de 8 (todas las cortas y medias). Coqui, con el
   modelo más ligero disponible en español (`es/css10/vits`), tiene latencias similares en
   cortas/medias pero **excede el techo de 10s en ambos guiones largos** (p95 11.98s y
   15.24s) — ver `resultados/tabla_resultados_consolidada.md`.
2. **Calidad de pronunciación de cifras (requisito explícito RF-01/ADR-014)**: Coqui
   `es/css10/vits` **no tiene dígitos en su vocabulario** y los descarta silenciosamente
   (fallo duro, confirmado por inspección del tokenizer). Piper, vía el frontend fonético
   espeak-ng, sí sintetiza los dígitos (aunque requiere que el guión los presente ya
   normalizados a palabras/dígitos-espaciados para pronunciarlos correctamente — ver
   `resultados/rubrica_calidad.md`). Ambos requieren normalización previa, pero el modo de
   fallo de Coqui es más silencioso/peligroso (el número desaparece del audio) que el de
   Piper (se pronuncia mal, pero se pronuncia).
3. **Peso/dependencias**: Piper es una dependencia ligera (`onnxruntime` + binding C, sin
   `torch`), consistente con un despliegue CPU-only austero, mientras que Coqui arrastra
   `torch`+`torchaudio`+`transformers` con un pinning delicado (ver `notas_instalacion.md`)
   que añade riesgo operativo de mantenimiento continuo (rotura ante actualizaciones de
   `transformers`, ya observada durante este mismo spike).
4. **Confirma la hipótesis de PLAN-008/ADR-014**: Piper era el candidato principal
   (CPU-friendly, pre-evaluado en ADR-012); la evidencia de este spike lo confirma. Coqui
   queda documentado como comparativa que NO superó a Piper en este contexto CPU-only/es-CO.

### Hallazgo que el Lead debe conocer antes de aprobar ADR-014: NO existe voz "es-CO" real

Ninguna librería evaluada (Piper ni Coqui) tiene una voz colombiana auténtica en su catálogo
público. El valor `PIPER_VOICE=es_CO-pablo-medium` en `config.py` **no existe** (HTTP 404
confirmado contra el catálogo oficial). La recomendación de esta SPEC es usar `es_ES-davefx-medium`
como mejor resultado medido (rendimiento) de las opciones reales disponibles, aceptando el
trade-off de acento (España, no LatAm) — alternativa: `es_MX-ald-medium` o `es_MX-claude-high`
(acento mexicano, más cercano a LatAm que España) a cambio de latencias algo mayores en
párrafos largos (9.4-10.7s p95, más cerca del límite superior del techo). **Esta es una
decisión de producto/UX, no solo técnica, y se recomienda explícitamente que el Lead la
confirme al aprobar ADR-014**: ¿prioriza rendimiento con acento ibérico (`es_ES-davefx-medium`)
o cercanía dialectal LatAm con menos margen de latencia (`es_MX-ald-medium`)?

## 2. Techo de latencia recomendado dentro de 5-10s (Q4-b)

**Objetivo: 5 s. Aceptable: 10 s**, tal como sugiere PLAN-008 §12.4, con la siguiente
matización basada en datos: el techo de 5s se cumple de forma consistente solo para guiones
cortos y medios (hasta ~200 caracteres); los guiones largos (párrafo, ~600+ caracteres) rondan
6-7s con `es_ES-davefx-medium`, dentro del aceptable de 10s pero sin margen amplio,
**especialmente bajo carga CPU concurrente** (ver §3). Se recomienda:
- Guiones hasta ~200 caracteres: techo objetivo 5s (Piper lo cumple holgadamente, p95<=3.6s).
- Guiones de 200-650 caracteres: techo aceptable 10s (Piper cumple con margen de ~2-3s sin
  concurrencia; el margen se reduce bajo concurrencia, ver §3).
- Guiones más largos que ~650 caracteres (el guión largo más extenso probado): no evaluados;
  se recomienda acotar la longitud sintetizable en SPEC-069 en ese orden de magnitud como
  medida preventiva (ver plan de contingencia, vía (3) del R-83).

## 3. Coste de CPU concurrente y dimensionado de `tts:jobs` (RF-04/R-84/CE-86)

**LIMITACIÓN**: no se pudo medir con los workers reales (ver `notas_instalacion.md` §5); se
usó una carga CPU sintética como proxy (3 procesos saturando CPU en una máquina de 4 vCPU).
Resultado: la latencia de síntesis de Piper sube ~87% en promedio bajo esa carga (rango
+58%..+103%), lo que en el peor caso (guión largo) llevaría la latencia de síntesis de ~3.6s
a ~6.4s, y el e2e (con transcodificación) de ~6.8-7.2s a un estimado de ~9-10s — **cerca o
en el límite del techo aceptable de 10s** si además hay otro TTS corriendo en paralelo.

**Recomendación de dimensionado inicial para SPEC-069**: **concurrencia de `tts:jobs` = 1**
(un solo job TTS a la vez) en esta máquina de 4 vCPU compartida con STT batch/RAG/sentimiento,
al menos hasta que se pueda re-medir con los workers reales corriendo (recomendado como parte
de SPEC-071/no-regresión, con acceso a un entorno con Docker). Complementar con throttling por
prioridad si la cola de STT/RAG tiene picos, priorizando STT/RAG (funciones ya en producción)
sobre TTS (nueva, opt-in, background, tolera esperar) en caso de contención.

## 4. Plan de contingencia (R-83) — ¿cuál aplica?

**Ninguna vía de contingencia dura se activa: Piper SÍ cumple el techo de 10s con calidad
aceptable** (condicionada a normalización previa de cifras/siglas en el guión, requisito ya
identificado para SPEC-069, no un fallo de motor). Por tanto:

- **(1) Relajar el techo a best-effort**: NO necesario como primera medida, pero SE
  RECOMIENDA como salvaguarda operativa para el escenario de concurrencia real medido en
  producción (si al re-medir con workers reales el guión largo excede 10s bajo contención,
  aplicar esta vía antes que degradar el motor, ya que el audio es asíncrono y el agente no
  quedó bloqueado, Q1-C).
- **(2) Degradar a motor más ligero (eSpeak-NG)**: NO aplica — Piper ya es la opción CPU-friendly
  más ligera que cumplió; no hace falta bajar más. eSpeak-NG no se evaluó (la SPEC solo lo
  pide "si ambos incumplen", y Piper sí cumple).
- **(3) Acotar la longitud sintetizable**: SE RECOMIENDA aplicar de forma preventiva en
  SPEC-069 — limitar a un máximo razonable (p. ej. ~650-800 caracteres, el rango probado aquí)
  y hacer caer a "solo texto" cualquier guión más largo, en vez de arriesgar exceder el techo
  en producción con guiones no probados.
- **(4) Degradar a "solo texto"**: NO aplica como vía general (el motor sí es viable); queda
  como fallback puntual solo para guiones que excedan el límite de longitud de (3), que es
  exactamente el diseño que ya contemplaba PLAN-008 §2.IN.3 (`tts_estado=error` cae a texto).

**Conclusión**: se activa parcialmente la vía (3) (acotar longitud, preventivo) y se deja
preparada la vía (1) (relajar techo) como salvaguarda si la medición con workers reales en un
entorno con Docker (a cargo de QUICKSILVER/HAWKEYE en SPEC-071) confirma que la concurrencia
real es peor que la estimada aquí. No se requiere degradar de motor ni caer a solo-texto como
comportamiento por defecto.

## 5. Resumen para ADR-014 / SPEC-068

- Motor: **Piper TTS 1.8.0**.
- Voz: **`es_ES-davefx-medium`** (recomendada por rendimiento) — **alternativa a confirmar por
  el Lead**: `es_MX-ald-medium` (más cercana a LatAm, algo más lenta).
- Parámetros: `SynthesisConfig()` por defecto, `use_cuda=False`, proceso persistente (no CLI
  por petición).
- Techo: objetivo 5s (guiones cortos/medios), aceptable 10s (guiones largos hasta ~650-800
  caracteres); guiones más largos se acotan/caen a texto.
- Concurrencia inicial `tts:jobs`: 1 (a re-validar con workers reales en SPEC-071).
- Corrección de `config.py`: `PIPER_VOICE=es_CO-pablo-medium` debe reemplazarse — no existe.
- Normalización de texto (nombres ya están bien; cifras/siglas requieren expansión previa a
  palabras) es un requisito nuevo a incluir en el alcance de SPEC-069, no cubierto hoy.
