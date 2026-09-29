# SPEC-072 — Documentación, runbook (motor/latencia/throttling/retención/disclaimer), limpieza de residuos documentada, simulador local sin egress y deploy on-prem 🔴 SENSIBLE

- Estado: CERRADA — runbook (motor/latencia/throttling/retención/disclaimer/troubleshooting), limpieza de residuos documentada y simulador local (verificado funcionando contra el motor real) entregados; el orquestador corrigió 5 errores reales en el runbook generado (rutas sin `/rag/`, endpoint inventado, campo de body incorrecto, job de purga inexistente). **Deploy on-prem (RF-04) diferido**: el Lead lo ejecutará de forma independiente con los secretos reales — mismo criterio que SPEC-066/PLAN-007 (el agente no genera/inventa secretos de producción, C3). Resto de criterios de aceptación cumplidos. Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE, DAREDEVIL · Prioridad: ALTA · Tipo: DOCS/OPS/DEPLOY · Fase: F5
- Deriva de: PLAN-008 (F5, §2.IN.11, §4, §9, §10, CE-84/CE-87) · Clasificación: SENSIBLE (`.no-externo`) · ADR-014/ADR-005/ADR-006/ADR-009/ADR-012
- APROBADO SPEC-072 por el Lead (bloque PLAN-008) — 2026-09-28.

## Objetivo

Cerrar el Entregable #6 con la **documentación operativa** y el **deploy on-prem**: un **runbook** que registre el **motor TTS elegido** (SPEC-067), el **techo de latencia**, el **throttling/concurrencia** de `tts:jobs`, la **retención por defecto (no persistir)** y el **disclaimer de voz sintética** (marca ligera); la **limpieza de residuos de config documentada** (`TTS_MODE`/`TTS_VRAM_FRACTION`/`PIPER_VOICE`, qué se quitó/reemplazó y por qué); un **simulador local verificable sin egress** de inferencia (síntesis + envío simulado a WhatsApp); y el **deploy on-prem** con **aprobación explícita del Lead** (cambio sensible → notificación Telegram, C6).

## Contexto

Sigue el patrón de cierre del proyecto (SPEC-061/066): runbook + simulador + deploy on-prem. El servicio TTS corre en `ia_internal internal:true` (sin egress) y la subida usa `app/integrations/whatsapp/` (`graph.facebook.com`, ADR-006). La limpieza de residuos `TTS_*` se **decidió/implementó** en SPEC-068 (config.py líneas 420–439); esta SPEC la **documenta** en el runbook (para operadores) y verifica que el despliegue no reintroduce claves GPU. El simulador debe permitir validar el slice end-to-end (guion aprobado → clip OGG/Opus generado local → subida simulada) **sin internet de inferencia**, reutilizando el enfoque de simuladores previos (SPEC-034/043/061). El deploy es un cambio sensible (nuevo servicio de voz de salida): requiere aprobación del Lead y notificación (C6).

## Alcance

### IN
- **Runbook del Entregable #6:** motor TTS elegido (SPEC-067) + voz + versiones; techo de latencia efectivo y su origen (SPEC-067); configuración de `tts:jobs` (throttling/concurrencia) y cómo ajustarla; política de **retención por defecto = no persistir** y qué implica activar la persistencia por auditoría (cifrado + SPEC-041); **disclaimer de voz sintética** (texto/marca ligera, ADR-014/SPEC-070); feature-flag de la UX de audio (cómo activar/desactivar, flag OFF = texto intacto); procedimiento de operación de ambas rutas híbridas; troubleshooting (`tts_estado="error"`, timeouts, formato OGG/Opus).
- **Limpieza de residuos documentada:** en el runbook y en el CHANGELOG/notas de deploy, qué claves `TTS_*` se eliminaron/reemplazaron (`TTS_VRAM_FRACTION` eliminada; `TTS_MODE` reemplazada/eliminada; `PIPER_VOICE` re-validada/renombrada según SPEC-067/068), por qué (CPU-only, ya no GPU/VRAM) y cómo migrar cualquier `.env` existente; verificación de que `.env.example` y `docker-compose.yml` no reintroducen claves GPU en el bloque TTS.
- **Simulador local sin egress:** herramienta/documentación para ejecutar el slice end-to-end localmente (guion aprobado → síntesis local con el motor de SPEC-067 → clip OGG/Opus → subida **simulada** a WhatsApp), sin ninguna llamada a internet de inferencia; verifica el formato OGG/Opus (R-88) y sirve de smoke test operativo.
- **Deploy on-prem (Docker Compose):** despliegue del servicio TTS en `ia_internal internal:true` (sin egress), pesos/voces montados por volumen (sin `pull` en runtime, patrón ADR-012), variables por env sin secretos en código (C3), con **aprobación explícita del Lead** y **notificación Telegram** (C6, cambio sensible).
- **Actualización de OpenAPI/notas** si el envío de audio expone/cambia contrato de endpoints (coordinado con SPEC-069/070), en la línea de SPEC-066.

### OUT
- Implementación del servicio/UX/pruebas (SPEC-069/070/071), decisión de motor (SPEC-067), ADR/datos/config (SPEC-068 — aquí solo se **documenta** la limpieza).
- Cualquier TTS de terceros / egress nuevo (PROHIBIDO).
- Persistir el clip por defecto (documentado como no-persistir; la persistencia por auditoría es opcional bajo SPEC-041).

## Dependencias
- Depende de SPEC-067 (motor/latencia/throttling a documentar), SPEC-068 (residuos limpiados a documentar), SPEC-069 (servicio/envío a operar), SPEC-070 (feature-flag/disclaimer a documentar) y SPEC-071 (evidencia verde requerida antes de deploy). Se ancla en ADR-005/006/009/012/014. Cierra el Entregable #6.

## Requisitos funcionales
- RF-01 El runbook documenta motor/latencia/throttling/retención/disclaimer y la operación de ambas rutas híbridas + troubleshooting.
- RF-02 La limpieza de residuos `TTS_*` queda documentada (qué/por qué/cómo migrar el `.env`); `.env.example`/`docker-compose.yml` no reintroducen claves GPU en el bloque TTS.
- RF-03 El simulador local ejecuta el slice end-to-end sin egress de inferencia y verifica el formato OGG/Opus.
- RF-04 El deploy on-prem levanta el servicio TTS en `ia_internal internal:true` (sin egress), con pesos/voces por volumen y sin secretos en código, tras aprobación del Lead y notificación C6.

## Requisitos no funcionales
- RNF-01 Cero egress: el simulador y el deploy no introducen salidas externas de voz; TTS de terceros PROHIBIDO; `check-externos-backend.sh` verde (verificado en SPEC-071).
- RNF-C3 Sin secretos en docs/simulador/compose; solo variables por env; ejemplos con placeholders.
- RNF-C6 El deploy sensible requiere aprobación explícita del Lead + notificación Telegram.
- RNF-REPRO El runbook y el simulador permiten reproducir la operación y el smoke test de forma determinista.

## Criterios de aceptación (verificables)
- [ ] Existe el runbook con motor/latencia/throttling/retención/disclaimer, operación de ambas rutas híbridas, feature-flag y troubleshooting.
- [ ] La limpieza de residuos `TTS_*` está documentada; `.env.example` y `docker-compose.yml` no contienen claves GPU (`TTS_VRAM_FRACTION`) en el bloque TTS; hay guía de migración del `.env`.
- [ ] El simulador local ejecuta guion→clip OGG/Opus→subida simulada **sin egress** de inferencia y verifica el formato.
- [ ] El deploy on-prem levanta el servicio TTS en `ia_internal internal:true` (sin egress), pesos/voces por volumen, sin secretos en código.
- [ ] El deploy se ejecuta **solo** tras aprobación explícita del Lead, con notificación Telegram (C6).
- [ ] `check-externos-backend.sh` verde tras el deploy (sin egress de voz).

## Notas de seguridad (C2/C3)
- C2: el runbook documenta la retención (no persistir por defecto; purga/anonimización si se persiste, SPEC-041/058).
- C3: sin secretos en docs/compose/simulador; variables por env con placeholders; token de Graph API solo en el módulo WhatsApp.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: el servicio TTS se despliega en `ia_internal internal:true` (sin ruta a internet); la única salida es la subida por `app/integrations/whatsapp/` a `graph.facebook.com` (ADR-006, transporte ya autorizado). El simulador no llama a terceros; TTS de terceros PROHIBIDO (ADR-012). Deploy sensible → aprobación del Lead + C6.

## Riesgos
- R-81 (fuga de egress de voz): deploy en `ia_internal internal:true`; `check-externos-backend.sh` verde tras deploy; simulador sin egress.
- R-87 (residuos de config GPU): documentación de limpieza + verificación de que `.env.example`/compose no reintroducen claves GPU.
- R-88 (formato incompatible): el simulador verifica OGG/Opus antes del deploy.
- R-DEPLOY (deploy sensible sin aprobación): gate C6 — aprobación explícita del Lead + notificación Telegram antes de desplegar.

## Checkpoints aplicables
- C2 (borrado lógico/retención documentada). C3 (sin secretos). C4 (criterios verificables). C6 (deploy sensible → aprobación del Lead + notificación Telegram). C8 (origen PLAN-008 / `prompt-lab/prompts/PROMPT-008-TTS-NOTAS-VOZ.md`).
