# ADR-006 — Excepción acotada a `.no-externo` para el TRANSPORTE del canal WhatsApp/Meta

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-003.md` (§3.2/§3.3/§3.4, F0/F4/F7, riesgo R-31, CE-33/CE-35), `SPEC-024`, `SPEC-026`, `SPEC-029`, `SPEC-032`, `SPEC-033`

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

La clasificación **SENSIBLE** (`.no-externo`) prohíbe cualquier inferencia externa y, más ampliamente, que
los componentes que procesan datos personales salgan a internet (garantizado técnicamente por **ADR-005**:
`ia_internal internal:true` + firewall host + auditoría). Sin embargo, el Entregable #3 integra el **canal
real WhatsApp Business Cloud API**, que **exige egress a `graph.facebook.com`** para (a) recibir por webhook
y (b) enviar mensajes por la Graph API. Sin esa salida, el canal real es imposible.

Se necesita decidir cómo habilitar ese egress **sin romper la política SENSIBLE** ni abrir ruta a internet
para la IA. La distinción clave: el egress a Meta es **TRANSPORTE del canal** (el texto ya aprobado por el
agente viaja como lo haría por una operadora telefónica), **no una llamada de inferencia** a un tercero.

---

## Decisión

Se adopta una **excepción acotada y auditable** a `.no-externo`, con las siguientes reglas duras:

1. **Egress permitido SOLO desde `api` (webhook) y `wa_send_worker`**, y **SOLO** hacia el dominio
   `graph.facebook.com`. Ningún otro contenedor ni dominio tiene salida.
2. **La IA permanece totalmente aislada** (reafirma ADR-005): `ia` (Ollama), `rag_worker` y
   `sentiment_worker` viven en red sin egress (`ia_internal internal:true`), **nunca** se conectan a la red
   `app` que tiene salida, y **jamás** obtienen ruta a `graph.facebook.com` ni a internet. Como `app` gana
   egress, la topología se **endurece** (SPEC-024): los workers de IA quedan fuera de `app` (red intermedia
   sin salida hacia Postgres/Redis) y/o firewall host DROP para IA, verificado con prueba de egress vacío.
3. **Allowlist por RUTA de módulo** en `check-externos-backend.sh`: `graph.facebook.com` se permite **solo**
   dentro del módulo del conector WhatsApp (`app/services/whatsapp/` o `app/integrations/whatsapp/`); si
   aparece en cualquier otro módulo → **falla el CI** (transporte fuera del conector = fuga). El script sigue
   prohibiendo todas las APIs de inferencia externas en todo el código, y prohíbe que el conector importe/
   llame IA y que módulos de IA importen el cliente httpx de transporte.
4. **Firewall a nivel host** que garantiza que el único egress público sea el transporte a Meta desde
   `api`/`wa_send_worker`.
5. **Secretos del canal** (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
   `WHATSAPP_APP_SECRET`) SOLO en env/secret manager (C3), nunca en repo/logs.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **BSP intermediario (Twilio/360dialog)** | Un tercero **vería el contenido** de los mensajes (datos personales), lo que contradice SENSIBLE con más fuerza que el transporte directo a Meta. Añade otro procesador de datos. |
| **Prohibir todo egress (mantener `.no-externo` estricto)** | **Imposibilita el canal real** de WhatsApp: sin salida a `graph.facebook.com` no hay recepción/envío. Contradice el objetivo del Entregable #3. |
| **Proxy con allowlist a nivel de red sin distinción por módulo de código** | Insuficiente como garantía de código: no impide que el transporte se introduzca en módulos indebidos (p. ej. dentro de la IA). Se complementa con allowlist **por ruta** en el CI. |
| **Dar egress a toda la red `app`** | Amplía la superficie de salida a componentes que no lo necesitan; se restringe a `api`/`wa_send_worker` + allowlist. |

---

## Consecuencias

**Pros**
- Habilita el canal real WhatsApp **sin** romper la política SENSIBLE: la IA sigue sin salida (ADR-005).
- Egress mínimo, explícito y **auditable por ruta** (CI) + firewall host; regresiones rompen la build.
- Meta actúa solo como transporte; ningún tercero de inferencia ve el contenido para inferir.

**Cons / mitigaciones**
- Aparece un borde de egress nuevo (riesgo R-31) → invariante de topología §3.2, allowlist por ruta,
  firewall host, prueba de egress vacío desde IA + captura de red (SPEC-032/033).
- Depende del entorno (firewall host, red Docker) → se versiona y documenta (SPEC-024/034); revisión
  QUICKSILVER/BLACK WIDOW en el deploy.
- Cambio sensible → requiere aprobación explícita del Lead + notificación Telegram (C6).

**Criterio de verificación (objetivo y verificable)**
- **Prueba de egress:** un intento de salida desde `ia`/`rag_worker`/`sentiment_worker` hacia cualquier
  IP/dominio público **debe fallar** (timeout/deny), con evidencia en CI.
- `api`/`wa_send_worker` alcanzan `graph.facebook.com` y **ningún** otro dominio público (captura de red).
- `check-externos-backend.sh` en verde con allowlist por ruta; test negativo (transporte fuera del
  conector) **falla** la build.
- Ninguno de los 4 secretos WhatsApp aparece en repo/logs/docs (barrido BLACK WIDOW, SPEC-032).

---

## Referencias

- `PLAN-003.md` — §3.2 (invariante de topología), §3.3 (aislamiento IA), §3.4 (allowlist por ruta), R-31, CE-33/CE-35, DoD §6.
- `SPEC-024` — Infra de egress acotado + allowlist por ruta + aislamiento reforzado de IA.
- `SPEC-026` / `SPEC-029` — Webhook (borde entrante) / envío por Graph API (borde de egress).
- `SPEC-032` / `SPEC-033` — Auditoría de seguridad / prueba de egress.
- Relacionado: **ADR-005** (bloqueo de egress de IA, reafirmado), **ADR-004** (RLS multi-tenant), **ADR-007** (idempotencia/enrutado).
- `scripts/check-externos-backend.sh` — auditoría de "cero inferencia externa + transporte acotado".
