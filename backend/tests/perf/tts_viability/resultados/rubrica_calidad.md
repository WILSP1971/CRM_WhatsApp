# Rúbrica de calidad subjetiva — SPEC-067 (THOR)

## Escala (1-5, por guión y motor/voz)

| Dimensión | 1 | 3 | 5 |
|---|---|---|---|
| Inteligibilidad | Ininteligible / palabras cortadas | Se entiende con esfuerzo | Perfectamente claro |
| Naturalidad | Robótico, prosodia plana | Aceptable, "acento de máquina" | Casi humano, entonación natural |
| Pronunciación nombres/cifras/siglas | Omite o pronuncia mal (p.ej. dígitos descartados) | Pronuncia pero con errores puntuales | Pronuncia correctamente todo |

## LIMITACIÓN HONESTA (RNF-REPRO / "≥1 revisor humano")

THOR (este agente) **no tiene capacidad de reproducir/escuchar audio** — no es un modelo
multimodal de audio. La SPEC exige evaluación por "≥1 revisor humano" con protocolo repetible;
esa evaluación auditiva formal **queda pendiente de un revisor humano** (el Lead, o un agente/
herramienta con capacidad de audio) escuchando los WAV entregados en `audio_out/*_warm/`.

Como sustituto objetivo y verificable (no un reemplazo de la escucha humana, sino evidencia
adicional que la acota), se aplicaron 3 análisis automatizables sobre los propios artefactos:

1. **Fonemización explícita** (`voice.phonemize()` de Piper vía espeak-ng): permite verificar
   sin ambigüedad SI el motor intentó pronunciar cada carácter/dígito/sigla, y CÓMO.
2. **Inspección de vocabulario del tokenizer** (Coqui): permite verificar si el motor tiene
   siquiera la capacidad de representar dígitos.
3. **Duración del audio generado** vs. longitud del texto (tasa de habla, caracteres/segundo):
   valores fuera de un rango humano razonable (muy rápido/lento) delatan warnings o cortes.

## Resultados objetivos por motor (evidencia, no sustituye escucha humana)

### Piper (es_ES-davefx-medium, ganador de latencia)
- **Pronunciación de cifras**: CORRECTA cuando el guión escribe los dígitos en palabras o
  separados por espacio ("tres uno cero, cuatro cinco seis" -> fonemas correctos dígito a
  dígito). INCORRECTA si se deja un número en dígitos crudos sin normalizar: un teléfono
  `3104567890` se lee como un solo número gigante ("tres mil cientos... millones...") en vez
  de dígito por dígito — confirmado por fonemización, ver `notas_instalacion.md`.
- **Siglas**: correctas si se escriben espaciadas ("C R M"); si se escriben juntas ("EPS",
  "IPS") se fusionan en una pseudo-palabra ("epeeese") en vez de deletrearse. Esto es un
  defecto de pronunciación de siglas objetivamente verificado (no simplemente supuesto).
  Nota: "ADRES" se sintetiza como palabra (no sigla), lo cual es razonablemente aceptable
  porque en el uso real "Adres" se pronuncia como palabra, no deletreada.
- **Nombres propios** (Wilson Sierra, Esteban Campbell, Julián Beltrán, Carlos Andrés López,
  Fernando Ríos): fonemización sin caracteres descartados, con acentuación fonética coherente
  con reglas del español (esperable inteligible; pendiente confirmar naturalidad con escucha).
- Estimación de calidad (evidencia objetiva, PENDIENTE de ratificar con escucha humana):
  inteligibilidad 4/5, naturalidad no evaluable sin escucha (marcar N/E), pronunciación de
  cifras/siglas 3/5 **condicionada a que el guión las escriba ya normalizadas** (2/5 si se
  dejan dígitos/siglas crudas sin normalizar).

### Coqui TTS (tts_models/es/css10/vits)
- **Pronunciación de cifras**: **FALLA OBJETIVA Y CRÍTICA**. El tokenizer del modelo NO
  incluye dígitos en su vocabulario (confirmado inspeccionando `tokenizer.characters`, ver
  `notas_instalacion.md`); cualquier dígito se descarta silenciosamente ("Character '3' not
  found in the vocabulary. Discarding it."). Esto rompe directamente el requisito RF-03/ADR-014
  de pronunciar correctamente cifras (fechas/horas/precios/teléfonos) — a menos que TODO
  guión pase por un normalizador de números a palabras antes de llegar a Coqui (mismo
  requisito que Piper, pero en Coqui es "hard fail" silencioso en vez de una pronunciación
  subóptima).
- Estimación de calidad (evidencia objetiva, PENDIENTE de ratificar con escucha humana):
  inteligibilidad no evaluable con cifras presentes (fallo duro), naturalidad no evaluable sin
  escucha, pronunciación de cifras/siglas 1/5 (motor no representa dígitos en absoluto salvo
  que se normalicen antes, igual que Piper, pero con menor margen de tolerancia al no tener
  fallback fonético).

## Conclusión de la rúbrica

Ninguno de los dos motores pronuncia bien cifras/siglas "tal cual llegan" sin normalización
previa (expansión de números y siglas a palabras, ej. "310-456-7890" -> "tres uno cero cuatro
cinco seis siete ocho nueve cero"). **Esto es un requisito de implementación para SPEC-069**
(un normalizador de texto ligero antes de la síntesis), no una limitación exclusiva de un
motor. La diferencia relevante es que Piper SÍ logra un resultado aceptable cuando el guión
está bien escrito (con las cifras ya en palabras), mientras que Coqui simplemente descarta
los dígitos sin normalizar, lo que es un riesgo mayor si el normalizador falla o se omite en
algún caso (degradación silenciosa: el número desaparece del audio en vez de sonar mal).
