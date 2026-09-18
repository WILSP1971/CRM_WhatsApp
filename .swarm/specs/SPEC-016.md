# SPEC-016 — IA local self-hosted: Ollama/vLLM + modelo abierto + embeddings + egress auditable

- Estado: PROPUESTA · Responsable: CAPTAIN AMERICA · Colaboran: BLACK PANTHER, BLACK WIDOW, HAWKEYE, THOR, WOLVERINE · Prioridad: ALTA · Tipo: IA/BACKEND · Fase: F4
- Deriva de: PLAN-002 (F4) · Clasificación: SENSIBLE (`.no-externo`)

## Objetivo

Desplegar la inferencia 100% local: servidor **Ollama/vLLM** con un **modelo abierto** (Qwen2.5-7B-Instruct por defecto / Llama-3.1-8B) y **embeddings locales** (nomic-embed-text / e5), con **egress de red bloqueado** y **verificación auditable** de cero llamadas externas de inferencia.

## Contexto

Fase F4 (SENSIBLE — requiere aprobación explícita del Lead por tocar IA/egress). Es el único servicio que ejecuta inferencia y NO puede salir a internet (red Docker `internal: true` de SPEC-011). Habilita SPEC-017 (RAG), SPEC-018 (sentimiento) y SPEC-019 (borrador). Modelo y embeddings parametrizables por env; modelos montados por volumen local (nunca `pull` en runtime hacia internet). Base de CE-21.

## Alcance

### IN
- Servicio `ia` con Ollama (o vLLM) sirviendo un LLM abierto local por HTTP interno.
- Modelo por defecto Qwen2.5-7B-Instruct (parametrizable por env: modelo, quant, contexto).
- Embeddings locales (nomic-embed-text / e5) expuestos por HTTP interno.
- Fallback CPU con modelo cuantizado Q4 cuando no haya GPU/VRAM suficiente (parametrizable).
- Cliente interno tipado en la API para hablar con el servicio `ia` (generación y embeddings).
- Verificación AUDITABLE de cero inferencia externa: prueba de egress vacío + captura de red + `check-externos-backend.sh`.

### OUT
- Pipeline RAG (ingesta/chunking/recuperación/citas) — SPEC-017.
- Clasificación de sentimiento — SPEC-018.
- Borrador human-in-the-loop — SPEC-019.
- STT/TTS/VoiceBot (Fase 3).

## Dependencias
- Depende de SPEC-011 (contenedor IA + red interna sin egress) y SPEC-012 (pgvector/esquema para embeddings). Prerequisito de SPEC-017, SPEC-018, SPEC-019.

## Requisitos funcionales
- RF-07 El LLM local genera texto por HTTP interno sin salir a internet.
- RF El servicio de embeddings local devuelve vectores para un texto dado.
- RF El modelo y los embeddings son parametrizables por variable de entorno.
- RF Con hardware sin GPU, el sistema arranca con modelo cuantizado Q4 (fallback CPU).

## Requisitos no funcionales
- RNF-01 Cero inferencia externa (auditable); solo red interna.
- RNF-04 Latencia de generación/embeddings medida (p95 formal en SPEC-022, THOR).
- Secretos/config de IA SOLO en env (C3); modelos montados por volumen local.

## Criterios de aceptación (verificables)
- [ ] El servicio `ia` genera una respuesta del LLM por HTTP interno (127.0.0.1/red interna).
- [ ] El servicio de embeddings devuelve un vector de la dimensión esperada para un texto.
- [ ] Un `curl` desde el contenedor `ia` a un dominio externo (p.ej. `api.openai.com`, `8.8.8.8`) **falla** (timeout/deny).
- [ ] Una corrida de generación e2e no registra conexiones salientes del contenedor `ia` a IPs públicas (netstat/pcap/log).
- [ ] `check-externos-backend.sh` **falla** si se introduce un SDK/endpoint de inferencia de terceros.
- [ ] El modelo es intercambiable por env (Qwen2.5-7B / Llama-3.1-8B) sin cambios de código.
- [ ] Sin GPU, el sistema arranca con modelo Q4 y responde (latencia degradada documentada).

## Notas de seguridad (C2/C3)
- C3: config y credenciales del servicio IA SOLO en env; sin claves de API de terceros (no existen).
- C2: no aplica directamente (sin entidades transaccionales propias).

## Restricción SENSIBLE aplicable
- Inferencia 100% on-prem; contenedor IA sin egress; ningún tercero procesa texto ni genera embeddings. Evidencia auditable de "cero externos" (CE-21).

## Riesgos
- R-21 (GPU/VRAM insuficiente): fallback CPU Q4; modelo parametrizable por env.
- R-22 (fuga de egress IA): red `internal` + firewall host DROP + prueba de egress vacío + captura de red.
- R-27 (calidad del modelo en es-CO): Qwen2.5-7B por defecto; prompts afinados; modelo cambiable por env.

## Checkpoints aplicables
- C3 (sin secretos). C4 (criterios verificables). C6 (cambio sensible: IA/egress → aprobación Lead). C8 (origen PLAN-002).

## Nota de aprobación
- **SPEC SENSIBLE (IA/egress):** requiere aprobación explícita del Lead y notificación (`.claude/hooks/notify.sh`).
