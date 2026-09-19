# SPEC-024 — Infra de egress acotado + aislamiento reforzado de IA + auditoría de transporte 🔴 SENSIBLE

- Estado: PROPUESTA · Responsable: QUICKSILVER · Colaboran: BLACK PANTHER, BLACK WIDOW, WOLVERINE, HAWKEYE · Prioridad: CRÍTICA · Tipo: INFRA/SEGURIDAD · Fase: F0
- Deriva de: PLAN-003 (F0, §3.2/§3.3/§3.4) · Clasificación: SENSIBLE (`.no-externo`) · ADR-006

## Objetivo

Habilitar un **egress externo acotado y auditable** SOLO para el transporte del canal WhatsApp (`api` webhook + `wa_send_worker` → `graph.facebook.com`), reforzando el **aislamiento total de la IA** (Ollama, `rag_worker`, `sentiment_worker` sin ruta a internet) y evolucionando `check-externos-backend.sh` con **allowlist por ruta de módulo**.

## Contexto

El Entregable #2 dejó la IA aislada en `ia_internal internal:true` (ADR-005). Esta fase introduce la **única novedad estructural**: egress real a Meta como transporte del canal. Es una EXCEPCIÓN documentada a `.no-externo` (ADR-006) que **no afecta a la IA**. Hoy los workers de IA (`rag_worker`, `sentiment_worker`) están conectados a `app` e `ia_internal`; como `app` gana egress hacia Meta, este PLAN **endurece** la topología para que la IA nunca tenga salida.

## Alcance

### IN
- `docker-compose`: `wa_send_worker` y `api` (webhook) en la red `app` (con egress restringido por allowlist a `graph.facebook.com`).
- Aislamiento reforzado de IA: `ia`, `rag_worker`, `sentiment_worker` SOLO en red sin egress (fuera de `app`, hablan a Postgres/Redis por red intermedia sin salida), o firewall host DROP verificado (vía a decidir en ADR-006).
- Reverse proxy TLS (Caddy/Nginx/Traefik) exponiendo SOLO el path del webhook; nunca IA ni BD.
- `check-externos-backend.sh` evolucionado: mantiene `FORBIDDEN_URLS`/`FORBIDDEN_SDKS` de inferencia; **nueva allowlist de transporte** con `graph.facebook.com` permitido SOLO dentro del módulo del conector (`app/services/whatsapp/` o `app/integrations/whatsapp/`); FALLA si aparece fuera.
- `.env.example` con las 4 vars WhatsApp como placeholders (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`).
- Firewall host que garantiza que solo `api`/`wa_send_worker` salgan y SOLO a Meta.

### OUT
- Datos del canal (SPEC-025), lógica del webhook (SPEC-026), envío (SPEC-029).
- Barrido de seguridad consolidado (SPEC-032) y pruebas de egress (SPEC-033).

## Dependencias
- Depende de SPEC-011 (infra base) y ADR-005 (aislamiento IA). Habilita toda la ruta crítica de la fase. Se ancla en ADR-006.

## Requisitos funcionales
- RF-01 `docker compose up` levanta el stack con `wa_send_worker` en `app` y la IA sin egress.
- RF-02 El reverse proxy TLS expone únicamente el path del webhook.
- RF-03 `check-externos-backend.sh` permite `graph.facebook.com` solo en el módulo del conector y falla si aparece en otro sitio.

## Requisitos no funcionales
- RNF-01 IA 100% local: `ia`/`rag_worker`/`sentiment_worker` sin ruta a internet ni a `graph.facebook.com`.
- RNF-07 Portabilidad on-prem: todo reproducible con `docker compose up`.

## Criterios de aceptación (verificables)
- [ ] `docker compose up` levanta el stack; `wa_send_worker`/`api` en `app`, IA en red sin egress.
- [ ] Un intento de egress desde `ia`/`rag_worker`/`sentiment_worker` a IP/dominio público **falla** (timeout/deny).
- [ ] `api`/`wa_send_worker` alcanzan `graph.facebook.com`; NO alcanzan otros dominios públicos (allowlist/firewall).
- [ ] `check-externos-backend.sh` en verde: `graph.facebook.com` solo en el módulo del conector; **falla** si se inserta en otro módulo (test negativo).
- [ ] `check-externos-backend.sh` **falla** si el módulo del conector importa/llama a Ollama o IA, o si un módulo de IA importa el cliente httpx de transporte.
- [ ] El reverse proxy TLS expone solo el path del webhook (no `/metrics`, no IA, no BD).
- [ ] `.env.example` contiene las 4 vars WhatsApp como placeholders; ningún secreto real en repo.

## Notas de seguridad (C2/C3)
- C3: las 4 vars WhatsApp SOLO en env/secret manager con fail-fast `${VAR:?}`; nunca en repo/logs.
- C2: no aplica creación de entidades; se preserva borrado lógico del resto del stack.

## Restricción SENSIBLE / excepción de egress
- 🔴 SENSIBLE: EXCEPCIÓN ACOTADA (ADR-006): egress permitido SOLO desde `api`/`wa_send_worker` y SOLO a `graph.facebook.com` (transporte, no inferencia). `ia_internal internal:true` se mantiene; la IA jamás alcanza Meta ni internet. Requiere aprobación explícita del Lead + notificación Telegram (C6).

## Riesgos
- R-31 (fuga de egress hacia la IA): invariante de topología §3.2; firewall host DROP para IA; allowlist por ruta; prueba de egress vacío (SPEC-033).
- R-37 (tokens expuestos): `.env.example` con placeholders; secretos en env; barrido BLACK WIDOW (SPEC-032).

## Checkpoints aplicables
- C3 (secretos en env). C4 (criterios verificables). C6 (cambio sensible: egress externo, aprobación + Telegram). C8 (origen PLAN-003).
