# Notas de instalación y limitaciones — SPEC-067 (THOR)

Hardware: AMD EPYC (CPU-only, confirmado `torch.cuda.is_available() == False`), 4 vCPU, 7.8 GiB RAM.
Fecha de ejecución: 2026-09-28. Python 3.12.3.

## 1. Piper TTS — instalado en `backend/.venv` (venv compartido del backend)

```
backend/.venv/bin/pip install piper-tts
# Version instalada: piper-tts==1.8.0 (paquete oficial OHF-voice/piper1-gpl)
# Dependencias: onnxruntime, pathvalidate (sin torch, ligero)
```

Sin conflictos con el resto de dependencias del backend (`pip check` limpio antes y después).

### Descubrimiento importante: la voz `es_CO-pablo-medium` de `config.py` NO EXISTE

`config.py` (líneas 420-439, residuo de la fase GPU archivada PLAN-005) fija
`PIPER_VOICE=es_CO-pablo-medium` como valor por defecto. Al intentar descargarla:

```
backend/.venv/bin/python -m piper.download_voices --download-dir <dir> es_CO-pablo-medium
# -> urllib.error.HTTPError: HTTP Error 404: Not Found
```

Se confirmó consultando el catálogo oficial (`voices.json` de
`huggingface.co/rhasspy/piper-voices`) que **no existe ninguna voz `es_CO-*` ni `es_419-*`**.
El catálogo de voces es-* disponibles en Piper es:

```
es_AR-daniela-high
es_ES-carlfm-x_low
es_ES-davefx-medium
es_ES-mls_10246-low
es_ES-mls_9972-low
es_ES-sharvard-medium
es_MX-ald-medium
es_MX-ald-x_low
es_MX-claude-high
```

**No hay voz colombiana ni "LatAm genérica" en Piper.** Las candidatas más cercanas a LatAm
son `es_MX-*` (México) y `es_AR-daniela-high` (Argentina); España (`es_ES-*`) es la variante
dialectal más lejana de es-CO. Se descargaron y evaluaron 4 voces: `es_MX-ald-medium`,
`es_MX-claude-high`, `es_AR-daniela-high`, `es_ES-davefx-medium`.

**Esto es un hallazgo que ADR-014/SPEC-068 debe registrar explícitamente**: el config.py
residual asume una voz que nunca existió en el catálogo real de Piper (no es solo un residuo
de la fase GPU, es un dato inválido). No hay ninguna voz es-CO "auténtica" disponible en
Piper hoy; la decisión de motor de este spike recomienda la MENOS lejana dialectalmente
combinada con el mejor rendimiento medido (ver tabla de resultados), asumiendo el trade-off
de acento.

## 2. Coqui TTS — instalado en venv AISLADO `backend/tests/perf/tts_viability/.venv_coqui`

Se decidió NO instalar Coqui en el venv compartido del backend (`backend/.venv`) porque
requiere una cadena de dependencias pesada y potencialmente conflictiva (torch, torchaudio,
una versión específica de `transformers`) que no aporta valor productivo al venv real del
backend (Coqui es solo comparativa de este spike, no se llevará a producción salvo que gane
la decisión). Se creó un venv Python nuevo dedicado solo para esta evaluación.

### Pinning exacto que SÍ logró funcionar (reproducible)

```
python3 -m venv backend/tests/perf/tts_viability/.venv_coqui
.venv_coqui/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv_coqui/bin/pip install coqui-tts
.venv_coqui/bin/pip install "transformers==4.57.1"   # ver nota de "yanked" abajo
.venv_coqui/bin/pip install "coqui-tts[codec]"       # instala torchcodec
```

Versiones resultantes: `torch==2.14.0+cpu`, `torchaudio==2.11.0+cpu`, `coqui-tts==0.27.5`,
`transformers==4.57.1`.

### Incompatibilidad encontrada y cómo se resolvió (documentado para reproducibilidad)

`coqui-tts==0.27.5` en PyPI **no fija un techo de versión de `transformers`** (solo
`transformers>=4.57`), por lo que `pip install coqui-tts` resuelve por defecto a la última
versión (`5.17.0` al momento de esta prueba), que:

1. Ya no expone `transformers.pytorch_utils.isin_mps_friendly`, símbolo que el código interno
   de `coqui-tts` (capa XTTS/Tortoise, que se importa incluso si solo se usa un modelo VITS)
   sigue requiriendo → `ImportError` al hacer `import TTS`.
2. Bajando a `transformers==4.49.0` (muy antigua) falla con un error distinto:
   `ImportError: cannot import name 'is_torchcodec_available'` (símbolo introducido después).
3. `transformers==4.57.0`/`4.57.1` sí exponen ambos símbolos y permiten el import, pero
   **`4.57.0` está "yanked" (retirada) en PyPI** por un bug de instalación reportado por el
   propio proyecto Transformers; se usó `4.57.1` (inmediatamente posterior, no yanked) que
   resultó estable para este spike.
4. Con `torch==2.14` (release reciente), Coqui exige adicionalmente `torchcodec` para IO de
   audio (mensaje explícito: "From Pytorch 2.9, the torchcodec library is required for audio
   IO"); se resolvió instalando el extra `coqui-tts[codec]`.

**Conclusión sobre esta incompatibilidad**: no es una limitación del sandbox ni de la red,
es un problema real de compatibilidad de versiones publicadas de la librería `coqui-tts`
0.27.5 en PyPI (no fija techo superior de `transformers`), reproducible en cualquier entorno
que instale `pip install coqui-tts` "a secas" hoy. Cualquier despliegue futuro de Coqui debe
fijar explícitamente `transformers==4.57.1` (o validar una versión posterior estable) en
`requirements.txt`, no dejarlo sin pin.

### Modelo evaluado: `tts_models/es/css10/vits`

Catálogo de modelos Coqui en español/multilingües disponibles (`TTS.list_models()`):
`tts_models/es/mai/tacotron2-DDC`, `tts_models/es/css10/vits`, más 4 modelos multilingües
pesados (`xtts_v2`, `xtts_v1.1`, `your_tts`, `bark`) descartados para CPU-only por ser
órdenes de magnitud más pesados (varios GB, diseñados para GPU/clonación de voz — fuera de
alcance y prohibidos por ADR-012 §6 de todos modos). Se evaluó `es/css10/vits` (arquitectura
VITS, comparable a Piper) por ser el más ligero disponible en español puro.

**Hallazgo crítico de calidad (ver `rubrica_calidad.md`)**: el vocabulario del tokenizer de
este modelo **no incluye dígitos** (`0`-`9` ausentes de `tokenizer.characters.vocab`);
cualquier cifra en el texto se descarta silenciosamente con un warning
(`Character '3' not found in the vocabulary. Discarding it.`). Esto es un defecto duro para
el caso de uso (fechas/horas/precios/teléfonos son parte explícita de RF-01).

## 3. ffmpeg — NO estaba disponible en el sistema ni en el Dockerfile del backend

Se verificó `which ffmpeg` → no encontrado; se buscó en todo el filesystem → no existe binario
`ffmpeg`, solo librerías runtime de FFmpeg (`libavcodec60`, `libavutil58`, `libswresample4` vía
`dpkg -l`, sin el binario CLI). Se inspeccionó `backend/Dockerfile` → **no instala `ffmpeg`**
(solo `gcc postgresql-client curl`).

**Esto contradice la afirmación de SPEC-067 §Contexto** ("ffmpeg ya está presente en el stack
STT de #5") y de PLAN-008 (mismo texto) — no se encontró evidencia de que `ffmpeg` esté
instalado en ningún Dockerfile ni script del repo. Se recomienda que SPEC-069/072 verifiquen
esto explícitamente antes de asumir que la transcodificación a OGG/Opus está resuelta; puede
ser una instalación pendiente real, no solo un hecho ya cumplido.

Para poder medir la latencia de transcodificación real (requisito RF-03/R-88 de esta SPEC), se
descargó un binario **estático** de ffmpeg (no requiere apt/root) desde
`https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz` (build pública
conocida, usada ampliamente para CI sin privilegios de root), versión `ffmpeg-7.0.2-amd64-static`
con soporte `libopus` incluido. Se dejó en
`backend/tests/perf/tts_viability/tools/ffmpeg-7.0.2-amd64-static/ffmpeg` — es una herramienta
de este spike, no se instaló a nivel de sistema ni se tocó el Dockerfile de producción.

## 4. Egress durante la síntesis (RNF-01, cero egress)

La síntesis en sí (llamadas a `piper.synthesize_wav()` / `TTS.tts_to_file()`) y la
transcodificación con ffmpeg **no realizan ninguna llamada de red** — son operaciones 100%
locales sobre los modelos ya descargados a disco. Solo la fase de INSTALACIÓN (pip install,
descarga de voces .onnx / modelos .pth) requirió red, consistente con lo indicado en la
instrucción de esta tarea ("instalar herramientas no es egress de inferencia"). No se verificó
con una herramienta de captura de paquetes (tcpdump) por no tener privilegios; se verificó
por inspección de código (las funciones de síntesis no importan `requests`/`urllib` en el
call path) y por el hecho de que los benchmarks corrieron exitosamente sin conectividad
adicional una vez descargados los modelos.

## 5. Concurrencia con STT batch/RAG/sentimiento (RF-04/R-84/CE-86) — LIMITACIÓN

No fue posible levantar los workers reales (`stt_worker.py`, `rag_ingest_worker.py`,
`sentiment_worker.py`) para medir contención real: este sandbox no tiene acceso a Docker
(`permission denied` al conectar al socket de Docker) ni a una orquestación de
Redis/Postgres/Ollama corriendo en paralelo. Como proxy razonado, se generó carga CPU
sintética (3 procesos Python puros saturando CPU, en una máquina de 4 vCPU) y se re-midió la
latencia de síntesis de Piper (voz ganadora, `es_ES-davefx-medium`) bajo esa carga. Resultado:
la latencia de síntesis sube en promedio ~87% (rango +58%..+103%) respecto al baseline sin
carga — ver `resultados/piper_latencia_concurrente.json`. Esto es una ESTIMACIÓN, no una
medición exacta del workload real (STT con faster-whisper y RAG con embeddings/Ollama pueden
tener patrones de uso de CPU/memoria distintos a un burn-CPU puro), pero es razonable como
cota inferior del impacto esperado, dado que en ambos casos se satura el mismo recurso (CPU)
en la misma máquina de 4 cores.

## Resumen de motores efectivamente instalados y probados

| Motor | Instalado | Import OK | Síntesis OK | Notas |
|---|---|---|---|---|
| Piper TTS (piper-tts 1.8.0) | Sí (venv backend) | Sí | Sí, 4 voces, 8 guiones, 5 reps c/u | Sin conflictos |
| Coqui TTS (coqui-tts 0.27.5) | Sí (venv aislado) | Sí (con pinning) | Sí, 1 modelo es, 8 guiones, 5 reps c/u | Requirió pinning manual de transformers==4.57.1 + extra [codec]; vocabulario sin dígitos |
| eSpeak-NG (fallback) | NO evaluado | - | - | No fue necesario: Piper SÍ cumple el techo (ver decisión de motor); la SPEC solo pide evaluarlo "si ambos incumplen" |
