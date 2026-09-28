# SPEC-067 (THOR) — Spike de viabilidad TTS local en CPU: Piper vs Coqui

Evidencia reproducible del spike de viabilidad de TTS 100% local, CPU-only, es-CO/LatAm,
comparando Piper TTS (candidato principal) y Coqui TTS (comparativa), con banco de guiones
ficticios, medición de latencia real (media/mediana/p95) contra el techo ≤5-10s (PLAN-008 Q4-b)
y estimación del impacto de CPU concurrente con STT batch/RAG/sentimiento.

## ⚠️ Advertencia de espacio en disco (acción pendiente antes de comitear)

Este directorio pesa ~2.4 GB (venv aislado de Coqui `.venv_coqui/` ~1.8 GB por torch, modelos
de voz `voices/` ~394 MB, binario ffmpeg estático `tools/` ~202 MB). **`.gitignore` del
proyecto NO cubre estas rutas** (solo ignora `backend/.venv/`, el venv principal del backend).
Se recomienda añadir antes de cualquier `git add`:
```
backend/tests/perf/tts_viability/.venv_coqui/
backend/tests/perf/tts_viability/voices/
backend/tests/perf/tts_viability/tools/
backend/tests/perf/tts_viability/audio_out/
```
Solo el código (`scripts/`), los guiones (`scripts_guiones/`), los resultados (`resultados/`)
y los `.md` de este directorio deben versionarse; son ligeros y suficientes para reproducir.

## Índice de artefactos

- `scripts_guiones/banco_guiones.json` — banco de 8 guiones ficticios es-CO (cortos/medios/
  largos, con nombres propios/cifras/siglas, sin PII real, RF-01/RNF-C3).
- `scripts/bench_piper.py` — benchmark "cold" de Piper (CLI por invocación; deja evidencia
  del overhead de recarga de modelo, no representativo de latencia de servicio real).
- `scripts/bench_piper_warm.py` — benchmark "warm" de Piper (API Python, modelo cargado 1 vez
  por voz, como un worker persistente) + transcodificación real a OGG/Opus. **Es el que
  sustenta la decisión de motor.**
- `scripts/bench_coqui_warm.py` — benchmark "warm" equivalente para Coqui TTS.
- `scripts/bench_piper_concurrente.py` — mide latencia de Piper bajo carga CPU sintética
  concurrente (proxy de STT/RAG/sentimiento, ver limitación en `notas_instalacion.md`).
- `scripts/cpu_stress.py` — generador de carga CPU sintética usado por el script anterior.
- `scripts/consolidar_resultados.py` — genera la tabla consolidada CSV/MD desde los JSON.
- `resultados/*.json` — resultados crudos por motor/voz/guión (latencias, tamaños de archivo).
- `resultados/*_run.log` — logs de ejecución completos de cada benchmark.
- `resultados/tabla_resultados_consolidada.{csv,md}` — tabla final comparativa vs. techo 5/10s.
- `resultados/rubrica_calidad.md` — rúbrica de calidad subjetiva + hallazgos objetivos (nota:
  evaluación auditiva humana formal PENDIENTE, ver limitación explicada ahí).
- `resultados/piper_latencia_concurrente.json` — resultados de latencia bajo carga CPU.
- `notas_instalacion.md` — bitácora completa de instalación, versiones exactas fijadas,
  incompatibilidades encontradas y cómo se resolvieron, y limitaciones honestas del sandbox.
- `DECISION_MOTOR.md` — **decisión de motor final propuesta** + plan de contingencia aplicado.
- `voices/piper/*.onnx(.json)` — 4 voces Piper descargadas (es_MX-ald-medium, es_MX-claude-high,
  es_AR-daniela-high, es_ES-davefx-medium).
- `voices/coqui/` — caché de modelo Coqui descargado (`tts_models/es/css10/vits`).
- `tools/ffmpeg-7.0.2-amd64-static/` — binario estático de ffmpeg (el sistema no lo tenía).
- `audio_out/**/*.wav` y `*.ogg` — clips de audio generados (ficticios, sin PII, borrables).
- `.venv_coqui/` — venv Python aislado con el pinning exacto para que Coqui importe (ver
  `notas_instalacion.md` para el porqué del aislamiento y los comandos exactos).

## Cómo reproducir

```bash
# Piper (usa el venv del backend, ya tiene piper-tts==1.8.0 instalado)
cd backend
.venv/bin/python tests/perf/tts_viability/scripts/bench_piper_warm.py

# Coqui (requiere el venv aislado .venv_coqui, ver notas_instalacion.md para recrearlo)
cd tests/perf/tts_viability
.venv_coqui/bin/python scripts/bench_coqui_warm.py

# Tabla consolidada
cd backend
.venv/bin/python tests/perf/tts_viability/scripts/consolidar_resultados.py
```

## Resumen ejecutivo (ver DECISION_MOTOR.md para el detalle completo)

- **Motor recomendado: Piper TTS 1.8.0**, voz `es_ES-davefx-medium` (única combinación que
  cumple el techo ≤10s en las 8 categorías de guión probadas; p95 peor caso = 7.19s).
- **Coqui TTS** (`tts_models/es/css10/vits`) excede el techo de 10s en guiones largos
  (p95 11.98s/15.24s) y su tokenizer **no soporta dígitos** (descarta cifras silenciosamente).
- **Hallazgo crítico**: la voz `PIPER_VOICE=es_CO-pablo-medium` de `config.py` **no existe**
  en el catálogo real de Piper (HTTP 404); no hay ninguna voz "es-CO" auténtica disponible en
  ningún motor evaluado — se recomienda `es_ES-davefx-medium` (mejor rendimiento) o
  `es_MX-ald-medium` (más cercana a LatAm, algo más lenta), decisión de producto a confirmar
  por el Lead en ADR-014.
- **ffmpeg no estaba instalado** en el sistema ni en `backend/Dockerfile` (contradice lo
  asumido en SPEC-067/PLAN-008); se usó un binario estático descargado para medir con
  transcodificación real incluida.
- **Concurrencia CPU**: no se pudo medir con los workers reales (sin acceso a Docker en este
  sandbox); estimación con carga CPU sintética muestra +58%..+103% de latencia bajo
  contención — se recomienda `tts:jobs` concurrencia=1 como punto de partida para SPEC-069.
- **Plan de contingencia (R-83)**: NO se activa ninguna vía dura (Piper cumple el techo); se
  aplica preventivamente la vía (3) "acotar longitud" (~650-800 caracteres máx.) y se deja
  preparada la vía (1) "relajar techo a best-effort" como salvaguarda si la re-medición con
  workers reales en un entorno con Docker confirma peor contención que la estimada aquí.
- **Hallazgo adicional de seguridad/CI (fuera del alcance de esta SPEC pero relevante)**:
  `backend/check-externos-backend.sh` da **falso positivo RECHAZADO** de forma preexistente
  (confirmado independientemente de este spike, con y sin piper-tts instalado) porque escanea
  `backend/` completo incluyendo `backend/.venv/site-packages/` sin excluirlo, y el paquete
  `huggingface_hub` (ya presente como dependencia transitiva de `transformers`, usado por el
  stack STT/RAG real) contiene en su propio código fuente las URLs de proveedores en la nube
  que el script bloquea (openai.com, groq.com, huggingface.co, etc.). Es un falso positivo de
  higiene de CI, no una fuga de egress real (nada de eso se importa/ejecuta desde `app/`), pero
  se recomienda que WOLVERINE/BLACK WIDOW añadan una exclusión de `.venv`/`venv` al script.
